from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from publish_vk_playwright_strict import community_wall_url  # noqa: E402
from publish_vk_scheduled import get_required_env  # noqa: E402

TOPIC_DIR = PROJECT_ROOT / "Итоговые результаты" / "НДС - коды видов операций"
ARTICLE_FILE = TOPIC_DIR / "НДС - коды видов операций - статья - книга продаж.md"
COVER_FILE = TOPIC_DIR / "НДС - коды видов операций - обложка статьи v3 - Nano Banana Pro.png"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Строгая публикация статьи VK с обложкой.")
    parser.add_argument("--publish", action="store_true", help="Разрешить финальную публикацию.")
    parser.add_argument("--dry-run", action="store_true", help="Заполнить и проверить, но не публиковать.")
    return parser.parse_args()


def read_article() -> tuple[str, str]:
    raw = ARTICLE_FILE.read_text(encoding="utf-8").strip()
    lines = raw.splitlines()
    title = lines[0].lstrip("#").strip()
    body_lines = lines[1:]
    clean_lines: list[str] = []
    for line in body_lines:
        stripped = line.strip()
        if stripped.startswith("### "):
            clean_lines.append(stripped[4:].strip())
        elif stripped.startswith("## "):
            clean_lines.append(stripped[3:].strip())
        elif stripped.startswith("# "):
            clean_lines.append(stripped[2:].strip())
        else:
            clean_lines.append(line.rstrip())
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(clean_lines).strip())
    return title, body


def click_text(page: Page, text: str, timeout_ms: int = 5_000) -> bool:
    selectors = [
        f"text={text}",
        f"button:has-text('{text}')",
        f"[role=button]:has-text('{text}')",
    ]
    for selector in selectors:
        try:
            page.locator(selector).first.click(timeout=timeout_ms)
            return True
        except PlaywrightError:
            continue
    return False


def open_article_editor(page: Page, group_id: str) -> None:
    page.goto(community_wall_url(group_id), wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(3_000)
    page.locator("button[data-testid='posting_create_article_button']").first.click(timeout=10_000)
    page.wait_for_timeout(5_000)
    page.locator(".article_editor_canvas[contenteditable='true']").first.wait_for(state="visible", timeout=20_000)


def fill_article(page: Page, title: str, body: str) -> None:
    heading = page.locator(".article_editor_canvas h1").first
    heading.click(timeout=10_000)
    page.keyboard.insert_text(title)
    page.wait_for_timeout(500)

    paragraph = page.locator(".article_editor_canvas p").first
    paragraph.click(timeout=10_000)
    page.keyboard.insert_text(body)
    page.wait_for_timeout(4_000)


def open_publish_settings(page: Page) -> None:
    if not click_text(page, "Публикация", timeout_ms=5_000):
        raise RuntimeError("Не нашёл меню 'Публикация' в редакторе статьи.")
    page.wait_for_timeout(2_000)


def attach_cover(page: Page) -> None:
    if not COVER_FILE.exists():
        raise FileNotFoundError(COVER_FILE)

    inputs = page.locator("input[type='file'][name='photo']")
    try:
        count = inputs.count()
    except PlaywrightError:
        count = 0
    if count == 0:
        inputs = page.locator("input[type='file'][accept*='image']")
        count = inputs.count()
    if count == 0:
        raise RuntimeError("Не нашёл поле загрузки обложки статьи.")

    inputs.nth(count - 1).set_input_files(str(COVER_FILE), timeout=10_000)
    page.wait_for_timeout(10_000)


def publish_article(page: Page) -> str:
    publish_button = page.locator("button.article_ed_layer__publish_settings_publish").first
    publish_button.wait_for(state="visible", timeout=10_000)
    disabled = publish_button.get_attribute("disabled")
    classes = publish_button.get_attribute("class") or ""
    if disabled is not None or "disabled" in classes.lower():
        raise RuntimeError("Кнопка 'Опубликовать' не активна. Проверьте заголовок, текст и обложку.")
    publish_button.click(timeout=10_000)
    page.wait_for_timeout(12_000)
    return page.url


def main() -> int:
    args = parse_args()
    if not args.publish and not args.dry_run:
        raise SystemExit("Нужен флаг --dry-run или --publish.")

    title, body = read_article()
    group_id = get_required_env("VK_GROUP_ID")
    profile = PROJECT_ROOT / ".vk-browser-profile"
    debug_dir = PROJECT_ROOT / "output" / "vk-browser-debug"
    debug_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile),
            headless=False,
            viewport={"width": 1365, "height": 900},
            slow_mo=100,
        )
        page = context.pages[0] if context.pages else context.new_page()
        open_article_editor(page, group_id)
        fill_article(page, title, body)
        open_publish_settings(page)
        attach_cover(page)
        page.screenshot(path=str(debug_dir / "strict-article-before-publish.png"), full_page=True)

        if args.dry_run:
            print(debug_dir / "strict-article-before-publish.png")
            context.close()
            return 0

        url = publish_article(page)
        page.screenshot(path=str(debug_dir / "strict-article-after-publish.png"), full_page=True)
        context.close()

    print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
