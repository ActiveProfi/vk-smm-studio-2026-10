"""
Подготовка готовых черновиков VK из Supabase без VK_USER_TOKEN.

Скрипт:
- берет готовые записи из Supabase vk_drafts;
- сохраняет полный текст и медиа в output/vk-publication-packages/;
- по умолчанию НЕ открывает VK и НЕ кликает по интерфейсу VK.

Причина: интерфейс VK нестабилен для браузерной автоматизации. Основная надежная часть —
выборка из базы по status=ready и scheduled_for<=now.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib import parse, request

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from publish_vk_scheduled import (
    collect_image_urls_for_post,
    get_due_vk_drafts,
    get_required_env,
    mark_publish_problem,
    update_vk_draft,
)


PROJECT_ROOT = Path(__file__).resolve().parent
PROFILE_DIR = PROJECT_ROOT / ".vk-browser-profile"
MEDIA_DIR = PROJECT_ROOT / "output" / "vk-browser-media"
READY_DRAFTS_PREVIEW = PROJECT_ROOT / "output" / "vk-ready-drafts-preview.txt"
PACKAGES_DIR = PROJECT_ROOT / "output" / "vk-publication-packages"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


class PublishNotConfirmed(RuntimeError):
    """Пользователь не подтвердил, что запись реально опубликована в VK."""


def safe_filename(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ._ -]+", "_", value).strip(" ._")
    return (cleaned or fallback)[:80]


def guess_extension(url: str, content_type: str) -> str:
    lowered = url.lower().split("?", 1)[0]
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov", ".webm", ".m4v"):
        if lowered.endswith(ext):
            return ext
    if "png" in content_type:
        return ".png"
    if "webp" in content_type:
        return ".webp"
    if "gif" in content_type:
        return ".gif"
    if "video" in content_type:
        return ".mp4"
    return ".jpg"


def download_file(url: str, folder: Path, stem: str) -> Path:
    local_path = Path(url)
    if local_path.exists():
        return local_path

    folder.mkdir(parents=True, exist_ok=True)
    req = request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with request.urlopen(req, timeout=900) as response:
        content = response.read()
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0]

    ext = guess_extension(url, content_type)
    path = folder / f"{safe_filename(stem, 'media')}{ext}"
    path.write_bytes(content)
    return path


def collect_media_files(draft: dict) -> list[Path]:
    draft_id = str(draft["id"])
    folder = MEDIA_DIR / draft_id
    files: list[Path] = []

    image_urls = collect_image_urls_for_post(draft, reserve_slots_for_video=1 if draft.get("video_url") else 0)
    for idx, url in enumerate(image_urls, start=1):
        files.append(download_file(url, folder, f"image-{idx}"))

    video_url = (draft.get("video_url") or "").strip()
    if video_url:
        files.append(download_file(video_url, folder, "video-1"))

    return files


def build_publication_package(draft: dict) -> Path:
    draft_id = str(draft["id"])
    package_dir = PACKAGES_DIR / draft_id
    media_dir = package_dir / "media"
    package_dir.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True, exist_ok=True)

    text = extract_vk_post_text(draft.get("post_text") or "")
    if not text:
        raise ValueError("Пустой текст поста.")

    media_files = collect_media_files(draft)
    if not media_files:
        raise ValueError("Нет image_url/video_url для публикации.")

    copied_media: list[str] = []
    for media in media_files:
        target = media_dir / media.name
        if media.resolve() != target.resolve():
            shutil.copy2(media, target)
        copied_media.append(str(target))

    (package_dir / "post-text.txt").write_text(text, encoding="utf-8")
    (package_dir / "manifest.json").write_text(
        json.dumps(
            {
                "draft_id": draft_id,
                "topic": draft.get("topic"),
                "post_type": draft.get("post_type"),
                "visual_type": draft.get("visual_type"),
                "media_files": copied_media,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return package_dir


def community_url(group_id: str) -> str:
    group_id = group_id.strip().lstrip("-")
    return f"https://vk.com/club{group_id}"


def wait_for_vk_login(page: Page, group_id: str) -> None:
    page.goto(community_url(group_id), wait_until="domcontentloaded", timeout=120_000)
    time.sleep(2)
    if "login" not in page.url and "act=login" not in page.url:
        print("VK: сессия уже активна.")
        return

    print("\nVK попросил вход. Войдите в аккаунт администратора в открытом браузере.")
    print("После входа дождитесь страницы сообщества и вернитесь в это окно.")
    input("Когда вход выполнен, нажмите Enter здесь...")
    page.goto(community_url(group_id), wait_until="domcontentloaded", timeout=120_000)


def click_first_visible(page: Page, selectors: list[str], *, timeout_ms: int = 2_000) -> bool:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            locator.wait_for(state="visible", timeout=timeout_ms)
            locator.click(timeout=timeout_ms)
            return True
        except PlaywrightError:
            continue
    return False


def find_post_editor(page: Page):
    selectors = [
        "[contenteditable='true'][role='textbox']",
        "div[contenteditable='true']",
        "textarea",
    ]
    for selector in selectors:
        locators = page.locator(selector)
        try:
            count = min(locators.count(), 8)
        except PlaywrightError:
            continue
        for i in range(count):
            locator = locators.nth(i)
            try:
                if locator.is_visible(timeout=1_000):
                    return locator
            except PlaywrightError:
                continue
    raise RuntimeError("Не нашёл поле ввода поста на странице VK.")


def debug_page_state(page: Page, name: str) -> Path:
    folder = PROJECT_ROOT / "output" / "vk-browser-debug"
    folder.mkdir(parents=True, exist_ok=True)
    safe = safe_filename(name, "debug")
    path = folder / f"{safe}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
    except PlaywrightError:
        pass
    return path


def open_post_editor(page: Page) -> None:
    click_first_visible(
        page,
        [
            "text=Что у вас нового?",
            "text=Напишите что-нибудь",
            "text=Создать запись",
            "[aria-label*='запись']",
            "[data-testid*='post']",
        ],
        timeout_ms=3_000,
    )
    time.sleep(1)


def attach_files(page: Page, media_files: list[Path]) -> None:
    if not media_files:
        return

    # Сначала пробуем напрямую найти input[type=file]. В VK он часто скрытый.
    inputs = page.locator("input[type='file']")
    try:
        if inputs.count() > 0:
            inputs.first.set_input_files([str(p) for p in media_files])
            time.sleep(5)
            return
    except PlaywrightError:
        pass

    # Если input не появился, пробуем открыть системный выбор файла через кнопки VK.
    file_button_selectors = [
        "text=Фото/видео",
        "text=Фотография",
        "text=Фотографии",
        "text=Фото",
        "text=Видео",
        "text=Медиа",
        "text=Прикрепить",
        "button:has-text('Фото')",
        "button:has-text('Видео')",
        "[aria-label*='фото']",
        "[aria-label*='Фото']",
        "[aria-label*='видео']",
        "[aria-label*='Видео']",
        "[aria-label*='прикреп']",
        "[aria-label*='Прикреп']",
    ]
    for selector in file_button_selectors:
        try:
            with page.expect_file_chooser(timeout=2_500) as fc_info:
                page.locator(selector).first.click(timeout=2_500)
            fc_info.value.set_files([str(p) for p in media_files])
            time.sleep(5)
            return
        except PlaywrightError:
            continue

    clicked = click_first_visible(page, file_button_selectors, timeout_ms=2_000)
    time.sleep(1)

    inputs = page.locator("input[type='file']")
    if inputs.count() == 0:
        raise RuntimeError(
            "Не нашёл кнопку/поле прикрепления файлов. Открыл браузер: прикрепите файлы вручную "
            f"из папки {media_files[0].parent} и нажмите публикацию."
        )

    inputs.first.set_input_files([str(p) for p in media_files])
    if clicked:
        time.sleep(5)


def fill_post_text(page: Page, text: str) -> None:
    open_post_editor(page)
    try:
        editor = find_post_editor(page)
        editor.click(timeout=5_000)
    except RuntimeError:
        screenshot = debug_page_state(page, "post-editor-not-found")
        print("\nЯ не нашёл поле создания записи автоматически.")
        print(f"Скрин состояния сохранён: {screenshot}")
        print("В открытом браузере нажмите мышкой в поле/кнопку создания записи в сообществе.")
        input("Когда поле поста открыто и курсор стоит внутри текста записи, нажмите Enter здесь...")
    try:
        editor = find_post_editor(page)
        editor.fill(text, timeout=10_000)
    except PlaywrightError:
        page.keyboard.insert_text(text)
    time.sleep(1)


def publish_current_post(page: Page, *, auto_click: bool) -> bool:
    if not auto_click:
        print("\nПроверьте пост в браузере. Если всё верно, нажмите кнопку публикации вручную.")
        answer = input(
            "После РЕАЛЬНОЙ публикации напишите published и нажмите Enter. "
            "Если не публиковали — просто нажмите Enter: "
        ).strip().lower()
        if answer != "published":
            raise PublishNotConfirmed("Публикация не подтверждена, черновик оставлен в ready.")
        return True

    button_selectors = [
        "button:has-text('Опубликовать')",
        "button:has-text('Отправить')",
        "button:has-text('Поделиться')",
        "text=Опубликовать",
        "text=Отправить",
        "text=Поделиться",
    ]
    if not click_first_visible(page, button_selectors, timeout_ms=5_000):
        raise RuntimeError("Не нашёл кнопку публикации. Открыл браузер: нажмите публикацию вручную.")
    time.sleep(8)
    return True


def get_latest_wall_url(page: Page, group_id: str) -> str:
    group_id = group_id.strip().lstrip("-")
    pattern = re.compile(rf"/wall-{re.escape(group_id)}_\d+")
    links = page.locator("a[href*='wall-']")
    try:
        count = min(links.count(), 30)
    except PlaywrightError:
        return community_url(group_id)
    for i in range(count):
        try:
            href = links.nth(i).get_attribute("href") or ""
        except PlaywrightError:
            continue
        match = pattern.search(href)
        if match:
            return f"https://vk.com{match.group(0)}"
    return community_url(group_id)


def extract_vk_post_text(raw_text: str) -> str:
    """
    Старые черновики могли сохранить весь ответ агента: пост + объяснение + промпт для KIE.
    Для VK берём только раздел "Черновик поста", чтобы не публиковать служебные блоки.
    """
    text = raw_text.strip()
    markers = [
        "## 1. Черновик поста",
        "### 1. Черновик поста",
        "Черновик поста:",
    ]
    for marker in markers:
        if marker in text:
            text = text.split(marker, 1)[1].strip()
            break

    stop_patterns = [
        r"\n---\s*\n\s*##\s*2\.",
        r"\n---\s*\n\s*###\s*2\.",
        r"\n\s*##\s*2\.",
        r"\n\s*###\s*2\.",
        r"\n\s*##\s*Почему формат",
        r"\n\s*##\s*Рекомендац",
        r"\n\s*##\s*Промпт",
        r"\n\s*##\s*Что проверить",
        r"\n\s*###\s*Почему формат",
        r"\n\s*###\s*Рекомендац",
        r"\n\s*###\s*Промпт",
        r"\n\s*###\s*Что проверить",
        r"\n\s*Промпт для KIE",
        r"\n\s*Image prompt",
        r"\n\s*Video prompt",
        r"\n\s*Техническое задание",
    ]
    cut_at = len(text)
    for pattern in stop_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            cut_at = min(cut_at, match.start())
    text = text[:cut_at].strip()

    text = re.sub(r"^\s*#+\s*", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def publish_draft_in_browser(page: Page, draft: dict, group_id: str, *, auto_click: bool) -> str:
    post_text = extract_vk_post_text(draft.get("post_text") or "")
    if not post_text:
        raise ValueError("Пустой текст поста.")

    media_files = collect_media_files(draft)
    if not media_files:
        raise ValueError("Нет image_url/video_url для публикации.")

    page.goto(community_url(group_id), wait_until="domcontentloaded", timeout=120_000)
    time.sleep(4)
    fill_post_text(page, post_text)
    attach_files(page, media_files)
    publish_current_post(page, auto_click=auto_click)
    page.goto(community_url(group_id), wait_until="domcontentloaded", timeout=120_000)
    time.sleep(4)
    return get_latest_wall_url(page, group_id)


def draft_preview(draft: dict) -> str:
    text = extract_vk_post_text(draft.get("post_text") or "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) > 120:
        text = f"{text[:120]}..."
    media = []
    if (draft.get("image_url") or "").strip():
        media.append("image")
    if (draft.get("video_url") or "").strip():
        media.append("video")
    if not media:
        media.append("без медиа")
    return (
        f"id={draft.get('id')} | topic={draft.get('topic') or '-'} | "
        f"type={draft.get('post_type') or '-'} | media={'+'.join(media)} | text={text or '-'}"
    )


def write_ready_drafts_preview(drafts: list[dict]) -> Path:
    READY_DRAFTS_PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "Готовые черновики для публикации VK",
        f"Создано: {datetime.now(timezone.utc).isoformat()}",
        "",
    ]
    if not drafts:
        lines.append("Готовых черновиков нет.")
    for index, draft in enumerate(drafts, start=1):
        lines.extend(
            [
                f"--- Черновик {index} ---",
                f"id: {draft.get('id')}",
                f"topic: {draft.get('topic') or '-'}",
                f"post_type: {draft.get('post_type') or '-'}",
                f"visual_type: {draft.get('visual_type') or '-'}",
                f"image_url: {draft.get('image_url') or '-'}",
                f"video_url: {draft.get('video_url') or '-'}",
                "",
                "Текст, который пойдёт в VK:",
                extract_vk_post_text(draft.get("post_text") or "-"),
                "",
            ]
        )
    READY_DRAFTS_PREVIEW.write_text("\n".join(lines), encoding="utf-8")
    return READY_DRAFTS_PREVIEW


def ask_confirm_draft(draft: dict) -> bool:
    print("\nНайден черновик к публикации:")
    print(draft_preview(draft))
    answer = input("Публиковать именно этот черновик? Напишите yes и нажмите Enter: ").strip().lower()
    return answer in {"yes", "y", "да", "д"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Готовит VK-черновики из Supabase по расписанию.")
    parser.add_argument(
        "--login-only",
        action="store_true",
        help="Только открыть браузер и сохранить вход VK, без публикации.",
    )
    parser.add_argument(
        "--auto-click",
        action="store_true",
        help="Устарело: браузерная автопубликация отключена как нестабильная.",
    )
    parser.add_argument("--open-vk", action="store_true", help="Только открыть страницу сообщества после подготовки пакета.")
    parser.add_argument("--limit", type=int, default=5, help="Сколько готовых черновиков обработать за запуск.")
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Только показать готовые черновики из Supabase, без открытия VK и публикации.",
    )
    parser.add_argument(
        "--draft-id",
        help="Опубликовать только один конкретный черновик по id.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Не спрашивать подтверждение выбора черновика. Кнопку публикации в VK всё равно не нажимает без --auto-click.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        group_id = get_required_env("VK_GROUP_ID")
    except Exception as exc:  # noqa: BLE001
        print(f"Ошибка настроек: {exc}", file=sys.stderr)
        return 1

    if not args.login_only:
        try:
            drafts = get_due_vk_drafts(limit=args.limit)
        except Exception as exc:  # noqa: BLE001
            print(f"Ошибка чтения черновиков из Supabase: {exc}", file=sys.stderr)
            return 1

        if args.draft_id:
            drafts = [draft for draft in drafts if str(draft.get("id")) == args.draft_id]
        if not drafts:
            print("Нет готовых черновиков для публикации.")
            return 0

        print("\nГотовые черновики, которые подходят под фильтр status=ready и scheduled_for<=now:")
        for draft in drafts:
            print("-", draft_preview(draft))
        preview_path = write_ready_drafts_preview(drafts)
        print(f"\nПолный текст черновиков сохранён здесь: {preview_path}")
        if args.list_only:
            print("\nЭто был только просмотр. VK не открывали и ничего не публиковали.")
            return 0

        selected_drafts = []
        for draft in drafts:
            if args.auto_click or args.yes or ask_confirm_draft(draft):
                selected_drafts.append(draft)
            else:
                print(f"{draft.get('id')}: пропуск по вашему подтверждению.")
        if not selected_drafts:
            print("Вы не подтвердили ни один черновик. VK не открывали.")
            return 0
    else:
        selected_drafts = []

    if not args.login_only and not args.open_vk:
        for draft in selected_drafts:
            draft_id = str(draft["id"])
            try:
                package_dir = build_publication_package(draft)
                output_files = draft.get("output_files") or {}
                if not isinstance(output_files, dict):
                    output_files = {}
                output_files["vk_publication_package"] = str(package_dir)
                update_vk_draft(
                    draft_id,
                    {
                        "status": "ready",
                        "notes": f"Пакет для публикации подготовлен: {package_dir}",
                        "output_files": output_files,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                print(f"{draft_id}: пакет для публикации подготовлен -> {package_dir}")
            except Exception as exc:  # noqa: BLE001
                update_vk_draft(
                    draft_id,
                    {
                        "status": "ready",
                        "notes": f"Ошибка подготовки публикации VK: {exc}",
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                print(f"{draft_id}: ошибка -> {exc}", file=sys.stderr)
        print("Готово. VK не открывали, автоклики отключены.")
        return 0

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1365, "height": 900},
            slow_mo=120,
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            wait_for_vk_login(page, group_id)
            if args.login_only:
                print("Вход сохранён. Можно закрыть браузер и запускать публикацию.")
                input("Нажмите Enter, чтобы закрыть браузер...")
                return 0

            published_count = 0
            for draft in selected_drafts:
                draft_id = str(draft["id"])
                try:
                    package_dir = build_publication_package(draft)
                    output_files = draft.get("output_files") or {}
                    if not isinstance(output_files, dict):
                        output_files = {}
                    output_files["vk_publication_package"] = str(package_dir)
                    update_vk_draft(
                        draft_id,
                        {
                            "status": "ready",
                            "notes": f"Пакет для публикации подготовлен: {package_dir}",
                            "output_files": output_files,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    print(f"{draft_id}: пакет для публикации подготовлен -> {package_dir}")
                    if args.open_vk:
                        page.goto(community_url(group_id), wait_until="domcontentloaded", timeout=120_000)
                        print("Открыта страница сообщества. Автоклики по VK отключены.")
                except PublishNotConfirmed as exc:
                    update_vk_draft(
                        draft_id,
                        {
                            "status": "ready",
                            "notes": str(exc),
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    print(f"{draft_id}: не отмечен как published -> {exc}")
                except Exception as exc:  # noqa: BLE001
                    update_vk_draft(
                        draft_id,
                        {
                            "status": "ready",
                            "notes": f"Ошибка подготовки публикации VK: {exc}",
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                    print(f"{draft_id}: ошибка -> {exc}", file=sys.stderr)

            print("Готово. Автоматические клики по VK отключены.")
            return 0
        except PlaywrightTimeoutError as exc:
            print(f"Браузер слишком долго ждал VK: {exc}", file=sys.stderr)
            return 1
        finally:
            context.close()


if __name__ == "__main__":
    raise SystemExit(main())
