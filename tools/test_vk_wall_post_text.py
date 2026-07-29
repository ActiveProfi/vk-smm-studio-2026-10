"""Проверка wall.post через токен сообщества.

Скрипт публикует короткий тестовый текстовый пост только с флагом --confirm-post.
Токены в вывод не печатает.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib import parse, request


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
VK_API_BASE = "https://api.vk.com/method/"


def load_dotenv_file() -> None:
    if not ENV_FILE.exists():
        raise RuntimeError(f"Файл .env не найден: {ENV_FILE}")

    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"В .env не заполнено {name}")
    return value


def vk_api_call(method_name: str, params: dict[str, str | int]) -> dict:
    token = required_env("VK_COMMUNITY_TOKEN")
    api_version = os.environ.get("VK_API_VERSION", "5.199").strip() or "5.199"
    payload = dict(params)
    payload["access_token"] = token
    payload["v"] = api_version

    body = parse.urlencode(payload).encode("utf-8")
    req = request.Request(
        f"{VK_API_BASE}{method_name}",
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    with request.urlopen(req, timeout=60) as response:
        data = json.loads(response.read().decode("utf-8"))

    if "error" in data:
        raise RuntimeError(f"{method_name}: {json.dumps(data['error'], ensure_ascii=False)}")
    return data["response"]


def main() -> int:
    if "--confirm-post" not in sys.argv:
        print("Скрипт делает реальный тестовый пост в VK.")
        print('Для запуска используйте: py -3 ".\\tools\\test_vk_wall_post_text.py" --confirm-post')
        return 2

    load_dotenv_file()
    group_id = required_env("VK_GROUP_ID")
    owner_id = f"-{group_id}"
    marker = int(time.time())
    message = (
        "Тест автопостинга через VK API. "
        f"Пост будет удален автоматически. marker={marker}"
    )

    print("Проверяю wall.post через VK_COMMUNITY_TOKEN...")
    post_response = vk_api_call(
        "wall.post",
        {
            "owner_id": owner_id,
            "from_group": 1,
            "message": message,
        },
    )
    post_id = post_response.get("post_id")
    if not post_id:
        raise RuntimeError(f"wall.post вернул ответ без post_id: {post_response}")

    print(f"wall.post: OK, post_id={post_id}")
    print("Пробую удалить тестовый пост через API...")
    try:
        delete_response = vk_api_call(
            "wall.delete",
            {
                "owner_id": owner_id,
                "post_id": post_id,
            },
        )
        print(f"wall.delete: OK, response={delete_response}")
    except Exception as exc:  # noqa: BLE001
        print(f"wall.delete: не удалось удалить через API: {exc}")
        print(f"Удалите тестовый пост вручную: https://vk.com/wall{owner_id}_{post_id}")

    print("Итог: текстовый wall.post через токен сообщества работает.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"Ошибка: {exc}", file=sys.stderr)
        raise SystemExit(1)
