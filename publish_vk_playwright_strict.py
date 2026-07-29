"""
Строгая публикация VK через Playwright, когда VK API не даёт загрузить картинки.

Правила безопасности:
- открывает только страницу сообщества;
- берёт только один due-черновик из Supabase за запуск;
- не ходит в ленту, сообщения, поиск и другие разделы VK;
- если VK просит логин, останавливается и просит один раз запустить --login-only;
- после публикации отмечает черновик как published.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from publish_vk_browser_scheduled import (
    collect_media_files,
    community_url,
    debug_page_state,
    draft_preview,
    extract_vk_post_text,
    get_latest_wall_url,
)
from publish_vk_scheduled import get_due_vk_drafts, get_required_env, update_vk_draft


PROJECT_ROOT = Path(__file__).resolve().parent
PROFILE_DIR = PROJECT_ROOT / ".vk-browser-profile"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Строгая публикация VK через Playwright.")
    parser.add_argument("--login-only", action="store_true", help="Только открыть VK и сохранить вход.")
    parser.add_argument("--dry-run", action="store_true", help="Показать due-черновик, ничего не открывать.")
    parser.add_argument("--draft-id", help="Опубликовать конкретный due-черновик по id.")
    parser.add_argument("--publish", action="store_true", help="Разрешить реальный клик публикации.")
    return parser.parse_args()


def assert_vk_community_page(page: Page, group_id: str) -> None:
    url = page.url.lower()
    if "login" in url or "act=login" in url:
        raise RuntimeError("VK просит вход. Сначала запустите: py -3 publish_vk_playwright_strict.py --login-only")
    allowed = (
        f"vk.com/club{group_id}",
        f"vk.ru/club{group_id}",
        f"vk.com/wall-{group_id}",
        f"vk.ru/wall-{group_id}",
    )
    if not any(part in url for part in allowed):
        raise RuntimeError(f"Остановлено: открыта не страница сообщества. URL: {page.url}")


def community_wall_url(group_id: str) -> str:
    group_id = group_id.strip().lstrip("-")
    return f"https://vk.com/wall-{group_id}?own=1"


def open_community(page: Page, group_id: str) -> None:
    page.goto(community_wall_url(group_id), wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(3_000)
    assert_vk_community_page(page, group_id)


def click_first_visible(page: Page, selectors: list[str], *, timeout_ms: int = 3_000) -> bool:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            locator.wait_for(state="visible", timeout=timeout_ms)
            locator.click(timeout=timeout_ms)
            return True
        except PlaywrightError:
            continue
    return False


def open_editor(page: Page) -> None:
    selectors = [
        "button:has-text('Создать пост')",
        "text=Создать пост",
        "text=Что у вас нового?",
        "text=Напишите что-нибудь",
        "text=Создать запись",
        "button:has-text('Создать запись')",
        "[aria-label*='Создать запись']",
        "[aria-label*='запись']",
    ]
    if not click_first_visible(page, selectors, timeout_ms=4_000):
        screenshot = debug_page_state(page, "strict-editor-open-failed")
        raise RuntimeError(f"Не нашёл кнопку создания записи. Скрин: {screenshot}")
    page.wait_for_timeout(1_500)
    # VK может найти старый неотправленный черновик. Для автопоста нужен пустой редактор.
    click_first_visible(
        page,
        [
            "button:has-text('Начать заново')",
            "text=Начать заново",
        ],
        timeout_ms=2_000,
    )
    page.wait_for_timeout(2_000)


def find_editor(page: Page):
    selectors = [
        "[contenteditable='true'][role='textbox']",
        "[contenteditable='true']",
        "textarea",
    ]
    for selector in selectors:
        locators = page.locator(selector)
        try:
            count = min(locators.count(), 10)
        except PlaywrightError:
            continue
        for index in range(count):
            locator = locators.nth(index)
            try:
                if locator.is_visible(timeout=1_000):
                    return locator
            except PlaywrightError:
                continue
    screenshot = debug_page_state(page, "strict-editor-not-found")
    raise RuntimeError(f"Не нашёл поле текста записи. Скрин: {screenshot}")


def fill_text(page: Page, text: str) -> None:
    open_editor(page)
    editor = find_editor(page)
    editor.click(timeout=5_000)
    try:
        editor.fill(text, timeout=10_000)
    except PlaywrightError:
        page.keyboard.insert_text(text)
    page.wait_for_timeout(1_000)


def attach_media(page: Page, media_files: list[Path]) -> None:
    if not media_files:
        raise RuntimeError("Нет медиафайлов для прикрепления.")

    paths = [str(path) for path in media_files]
    input_selectors = [
        "input[data-testid='posting_base_screen_download_from_device']",
        "input[type='file'][accept*='image']",
        "input[type='file']",
    ]
    for selector in input_selectors:
        inputs = page.locator(selector)
        try:
            count = inputs.count()
        except PlaywrightError:
            count = 0
        for index in range(count):
            try:
                inputs.nth(index).set_input_files(paths, timeout=10_000)
                page.wait_for_timeout(8_000)
                return
            except PlaywrightError:
                continue

    button_selectors = [
        "text=Фото/видео",
        "text=Фотографии",
        "text=Фотография",
        "text=Фото",
        "button:has-text('Фото')",
        "[aria-label*='Фото']",
        "[aria-label*='фото']",
        "[aria-label*='Прикреп']",
        "[aria-label*='прикреп']",
    ]

    for selector in button_selectors:
        try:
            with page.expect_file_chooser(timeout=3_000) as chooser:
                page.locator(selector).first.click(timeout=3_000)
            chooser.value.set_files(paths)
            page.wait_for_timeout(8_000)
            return
        except PlaywrightError:
            continue

    screenshot = debug_page_state(page, "strict-media-attach-failed")
    raise RuntimeError(f"Не нашёл кнопку/поле прикрепления медиа. Скрин: {screenshot}")


def click_publish(page: Page) -> None:
    next_selectors = [
        "button[data-testid='posting_base_screen_next']",
        "button:has-text('Далее')",
        "text=Далее",
    ]
    click_first_visible(page, next_selectors, timeout_ms=4_000)
    page.wait_for_timeout(3_000)

    publish_selectors = [
        "button[data-testid='posting_base_screen_publish']",
        "button:has-text('Опубликовать')",
        "button:has-text('Отправить')",
        "button:has-text('Поделиться')",
        "text=Опубликовать",
        "text=Отправить",
        "text=Поделиться",
    ]
    if not click_first_visible(page, publish_selectors, timeout_ms=6_000):
        screenshot = debug_page_state(page, "strict-publish-button-not-found")
        raise RuntimeError(f"Не нашёл кнопку публикации. Скрин: {screenshot}")
    page.wait_for_timeout(10_000)


def publish_one(page: Page, draft: dict, group_id: str, *, allow_publish: bool) -> str:
    if not allow_publish:
        raise RuntimeError("Для реальной публикации нужен флаг --publish.")

    text = extract_vk_post_text(draft.get("post_text") or "")
    validate_clean_post_text(text)
    if not text:
        raise ValueError("Пустой текст поста.")

    media_files = collect_media_files(draft)
    if not media_files:
        raise ValueError("Нет image_url/video_url для публикации.")

    open_community(page, group_id)
    fill_text(page, text)
    attach_media(page, media_files)
    click_publish(page)
    open_community(page, group_id)
    return get_latest_wall_url(page, group_id)


def validate_clean_post_text(text: str) -> None:
    forbidden_markers = [
        "промпт для kie",
        "prompt",
        "nano banana",
        "техническое задание",
        "визуал:",
        "рекомендация по визуалу",
        "почему формат",
        "что проверить перед публикацией",
        "черновик поста:",
        "##",
        "###",
    ]
    lowered = text.lower()
    found = [marker for marker in forbidden_markers if marker in lowered]
    if found:
        raise RuntimeError(
            "Остановлено: в тексте для VK найдены технические маркеры: "
            + ", ".join(found)
        )


def update_as_published(draft: dict, post_url: str) -> None:
    output_files = draft.get("output_files") or {}
    if not isinstance(output_files, dict):
        output_files = {}
    output_files["vk_post_url"] = post_url
    output_files["vk_publish_mode"] = "playwright_strict"

    update_vk_draft(
        str(draft["id"]),
        {
            "status": "published",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "notes": None,
            "output_files": output_files,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def select_due_draft(draft_id: str | None) -> dict | None:
    drafts = get_due_vk_drafts(limit=10)
    if draft_id:
        drafts = [draft for draft in drafts if str(draft.get("id")) == draft_id]
    if not drafts:
        return None
    return drafts[0]


def main() -> int:
    args = parse_args()
    group_id = get_required_env("VK_GROUP_ID")

    if args.login_only:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(PROFILE_DIR),
                headless=False,
                viewport={"width": 1365, "height": 900},
                slow_mo=100,
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(community_url(group_id), wait_until="domcontentloaded", timeout=120_000)
            print("Войдите в VK под администратором сообщества, если вход ещё не выполнен.")
            input("Когда страница сообщества открыта под админом, нажмите Enter здесь...")
            context.close()
        return 0

    draft = select_due_draft(args.draft_id)
    if draft is None:
        print("Нет due-черновиков для публикации.")
        return 0

    print("Выбран due-черновик:")
    print("-", draft_preview(draft))

    if args.dry_run:
        print("Dry-run: браузер не открывали, публикации не было.")
        return 0

    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(PROFILE_DIR),
                headless=False,
                viewport={"width": 1365, "height": 900},
                slow_mo=120,
            )
            page = context.pages[0] if context.pages else context.new_page()
            post_url = publish_one(page, draft, group_id, allow_publish=args.publish)
            update_as_published(draft, post_url)
            print(f"Опубликовано: {post_url}")
            context.close()
        return 0
    except PlaywrightTimeoutError as exc:
        print(f"VK слишком долго отвечал: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        update_vk_draft(
            str(draft["id"]),
            {
                "status": "ready",
                "notes": f"Ошибка strict Playwright публикации: {exc}",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
