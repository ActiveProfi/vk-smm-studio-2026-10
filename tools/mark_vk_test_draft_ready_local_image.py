"""
Возвращает тестовый черновик в ready и ставит локальную тестовую PNG-картинку.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from publish_vk_scheduled import update_vk_draft  # noqa: E402
from tools.create_test_png import OUT as TEST_IMAGE  # noqa: E402
from tools.create_test_png import main as create_test_png  # noqa: E402


def main() -> int:
    draft_id = sys.argv[1] if len(sys.argv) > 1 else "1afa765b-2710-4401-9ad6-9223476b4424"
    if not TEST_IMAGE.exists():
        create_test_png()
    now = datetime.now(timezone.utc).isoformat()
    update_vk_draft(
        draft_id,
        {
            "status": "ready",
            "image_url": str(TEST_IMAGE),
            "notes": None,
            "scheduled_for": now,
            "updated_at": now,
        },
    )
    print(f"{draft_id} -> ready")
    print(TEST_IMAGE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
