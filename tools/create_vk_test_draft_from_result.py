"""
Создаёт или обновляет тестовый ready-черновик VK из готовых файлов проекта.

Нужен для проверки браузерной публикации без повторной генерации через KIE.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from publish_vk_scheduled import supabase_request, update_vk_draft  # noqa: E402


TEXT_FILE = (
    PROJECT_ROOT
    / "Итоговые результаты"
    / "НДС - базовые понятия"
    / "НДС - базовые понятия - пост - какие операции облагаются НДС - для VK.txt"
)
IMAGE_LINK_FILE = (
    PROJECT_ROOT
    / "Итоговые результаты"
    / "НДС - базовые понятия"
    / "НДС - базовые понятия - инфографика - операции облагаемые НДС - ссылка.txt"
)


def read_image_url() -> str:
    for line in IMAGE_LINK_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("http"):
            return line
    raise RuntimeError(f"Не найдена ссылка на картинку в {IMAGE_LINK_FILE}")


def build_payload() -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "status": "ready",
        "publish_channel": "vk",
        "topic": "Какие операции облагаются НДС",
        "post_type": "razbor",
        "post_text": TEXT_FILE.read_text(encoding="utf-8").strip(),
        "visual_type": "image",
        "image_url": read_image_url(),
        "video_url": None,
        "input_data": {"source": "manual_test_from_ready_project_result"},
        "output_files": {
            "source_text": str(TEXT_FILE.relative_to(PROJECT_ROOT)),
            "source_image_link": str(IMAGE_LINK_FILE.relative_to(PROJECT_ROOT)),
        },
        "notes": None,
        "scheduled_for": now,
        "updated_at": now,
    }


def main() -> int:
    draft_id = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    payload = build_payload()
    if draft_id:
        update_vk_draft(draft_id, payload)
        print(draft_id)
        return 0

    rows = supabase_request("POST", "vk_drafts", payload=payload)
    if isinstance(rows, list) and rows:
        print(rows[0]["id"])
        return 0
    print(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
