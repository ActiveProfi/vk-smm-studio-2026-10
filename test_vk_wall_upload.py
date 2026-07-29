"""
Диагностика VK API для автопостинга: не публикует посты.
Проверяет groups.getById, photos.getWallUploadServer и video.save (только URL загрузки, без файла).

Запуск из папки проекта:
  py -3 test_vk_wall_upload.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from publish_vk_scheduled import (  # noqa: E402
    get_required_env,
    get_vk_access_token,
    load_dotenv_file,
    vk_api_call,
)


def main() -> int:
    load_dotenv_file()
    has_user = bool(os.environ.get("VK_USER_TOKEN", "").strip())
    has_comm = bool(os.environ.get("VK_COMMUNITY_TOKEN", "").strip())
    if has_user:
        mode = "используется VK_USER_TOKEN (приоритет)"
    elif has_comm:
        mode = "только VK_COMMUNITY_TOKEN (фото/видео на стену обычно недоступны — нужен VK_USER_TOKEN)"
    else:
        print("Ошибка: нет ни VK_USER_TOKEN, ни VK_COMMUNITY_TOKEN в .env", file=sys.stderr)
        return 1

    print("Режим:", mode)
    try:
        group_id = get_required_env("VK_GROUP_ID")
        token = get_vk_access_token()
    except ValueError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1

    tail = token[-4:] if len(token) >= 4 else ""
    print("Токен (маска):", f"{token[:6]}…{tail}")

    try:
        info = vk_api_call("groups.getById", {"group_id": group_id})
        print("groups.getById: OK", json.dumps(info, ensure_ascii=False)[:200])
    except Exception as e:  # noqa: BLE001
        print(f"groups.getById: ОШИБКА — {e}", file=sys.stderr)
        return 2

    try:
        upload = vk_api_call("photos.getWallUploadServer", {"group_id": group_id})
        if upload.get("upload_url"):
            print("photos.getWallUploadServer: OK (upload_url получен)")
        else:
            print("photos.getWallUploadServer: странный ответ без upload_url", upload)
    except Exception as e:  # noqa: BLE001
        print(f"photos.getWallUploadServer: ОШИБКА — {e}", file=sys.stderr)
        print(
            "\nОшибка 27 = метод недоступен с токеном сообщества — нужен VK_USER_TOKEN админа.\n"
            "Ошибка 15 = не хватает прав в токене — в scope: photos, wall, video, groups; "
            "по возможности offline.",
            file=sys.stderr,
        )
        return 3

    try:
        vs = vk_api_call(
            "video.save",
            {"group_id": group_id, "name": "vk-agent-test", "wallpost": 0},
        )
        if vs.get("upload_url"):
            print("video.save: OK (upload_url получен — право на загрузку видео есть)")
        else:
            print("video.save: нет upload_url в ответе", vs)
    except Exception as e:  # noqa: BLE001
        print(f"video.save: ОШИБКА — {e}", file=sys.stderr)
        print("Добавьте в scope пользовательского токена право video.", file=sys.stderr)
        return 4

    print("\nФото и видео на стену: проверки пройдены. Можно запускать publish_vk_scheduled.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
