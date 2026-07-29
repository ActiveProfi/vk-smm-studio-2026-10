from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from publish_vk_playwright_strict import community_wall_url  # noqa: E402
from publish_vk_scheduled import get_required_env  # noqa: E402

TOPIC_DIR = PROJECT_ROOT / "Итоговые результаты" / "НДС - коды видов операций"
ARTICLE_FILE = TOPIC_DIR / "НДС - коды видов операций - статья - книга продаж.md"
COVER_FILE = TOPIC_DIR / "НДС - коды видов операций - обложка статьи v3 - Nano Banana Pro.png"


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

    body = "\n".join(clean_lines).strip()
    body = re.sub(r"\n{3,}", "\n\n", body)
    return title, body


def main() -> int:
    if not COVER_FILE.exists():
        raise FileNotFoundError(COVER_FILE)

    group_id = get_required_env("VK_GROUP_ID")
    title, body = read_article()
    profile = PROJECT_ROOT / ".vk-browser-profile"
    debug_dir = PROJECT_ROOT / "output" / "vk-browser-debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    screenshot = debug_dir / "strict-article-filled.png"

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile),
            headless=False,
            viewport={"width": 1365, "height": 900},
            slow_mo=100,
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(community_wall_url(group_id), wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(3_000)
        page.locator("button[data-testid='posting_create_article_button']").first.click(timeout=10_000)
        page.wait_for_timeout(5_000)

        canvas = page.locator(".article_editor_canvas[contenteditable='true']").first
        canvas.wait_for(state="visible", timeout=20_000)

        heading = page.locator(".article_editor_canvas h1").first
        heading.click(timeout=10_000)
        page.keyboard.insert_text(title)
        page.wait_for_timeout(500)

        paragraph = page.locator(".article_editor_canvas p").first
        paragraph.click(timeout=10_000)
        page.keyboard.insert_text(body)
        page.wait_for_timeout(5_000)

        page.screenshot(path=str(screenshot), full_page=True)
        context.close()

    print(screenshot)
    print(title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
