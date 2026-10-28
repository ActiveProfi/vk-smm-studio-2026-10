"""Публикация и статистика ВКонтакте для веб-приложения."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib import parse, request
import json

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import publish_vk_scheduled as vk_pub  # noqa: E402

from webapp.services.post_format import prepare_post_text_for_vk  # noqa: E402


def resolve_token_and_group(
    user_token: str = "", user_group_id: str = ""
) -> tuple[str, str, str]:
    """
    Возвращает (token, group_id, source).
    source: channel | env_user | env_community
    """
    vk_pub.load_dotenv_file()
    token = (user_token or "").strip()
    source = "channel"
    if not token:
        token = os.environ.get("VK_USER_TOKEN", "").strip()
        source = "env_user" if token else ""
    if not token:
        token = os.environ.get("VK_COMMUNITY_TOKEN", "").strip()
        source = "env_community" if token else ""
    group_id = (user_group_id or "").strip() or os.environ.get("VK_GROUP_ID", "").strip()
    if not token:
        raise ValueError(
            "Не задан VK-токен. Вставьте его в настройках канала "
            "или добавьте VK_USER_TOKEN в файл .env"
        )
    if not group_id:
        raise ValueError(
            "Не задан ID группы ВК. Укажите его в настройках канала "
            "или добавьте VK_GROUP_ID в файл .env"
        )
    # ID группы может прийти как club123 / -123 / 123
    group_id = str(group_id).strip()
    if group_id.startswith("club"):
        group_id = group_id[4:]
    if group_id.startswith("-"):
        group_id = group_id[1:]
    return token, group_id, source


def _env_token_and_group(user_token: str = "", user_group_id: str = "") -> tuple[str, str]:
    """Приоритет: настройки канала в веб-кабинете, затем .env."""
    token, group_id, _source = resolve_token_and_group(user_token, user_group_id)
    return token, group_id


def test_connection(*, user_token: str = "", user_group_id: str = "") -> dict:
    """
    Проверка токена и группы: читаем название сообщества и число подписчиков.
    Если пользовательский токен из .env привязан к другому IP — пробуем токен сообщества.
    """
    vk_pub.load_dotenv_file()
    group_id = (user_group_id or "").strip() or os.environ.get("VK_GROUP_ID", "").strip()
    if group_id.startswith("club"):
        group_id = group_id[4:]
    if group_id.startswith("-"):
        group_id = group_id[1:]
    if not group_id:
        raise ValueError(
            "Не задан ID группы ВК. Укажите его в настройках канала "
            "или добавьте VK_GROUP_ID в файл .env"
        )

    candidates: list[tuple[str, str]] = []
    explicit = (user_token or "").strip()
    if explicit:
        candidates.append((explicit, "channel"))
    else:
        u = os.environ.get("VK_USER_TOKEN", "").strip()
        c = os.environ.get("VK_COMMUNITY_TOKEN", "").strip()
        if u:
            candidates.append((u, "env_user"))
        if c:
            candidates.append((c, "env_community"))

    if not candidates:
        raise ValueError(
            "Не задан VK-токен. Вставьте его в настройках канала "
            "или добавьте VK_USER_TOKEN / VK_COMMUNITY_TOKEN в .env"
        )

    last_error: Exception | None = None
    notes: list[str] = []
    token = ""
    source = ""
    groups = None

    for tok, src in candidates:
        try:
            groups = _vk_call_with_token(
                "groups.getById",
                {"group_id": group_id, "fields": "members_count,screen_name"},
                tok,
            )
            token = tok
            source = src
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            notes.append(f"{src}: {exc}")
            continue

    if groups is None:
        raise RuntimeError(str(last_error) if last_error else "Не удалось подключиться к ВК")

    source_label = {
        "channel": "токен из настроек канала",
        "env_user": "токен из .env (VK_USER_TOKEN)",
        "env_community": "токен из .env (VK_COMMUNITY_TOKEN)",
    }.get(source, source)

    if isinstance(groups, dict):
        items = groups.get("groups") or groups.get("items") or []
    else:
        items = groups or []
    if not items:
        raise RuntimeError("VK не вернул данные группы. Проверьте ID группы.")

    g = items[0]
    name = g.get("name") or "Без названия"
    screen = g.get("screen_name") or ""
    members = g.get("members_count")
    gid = g.get("id") or group_id

    can_post = None
    wall_error = ""
    try:
        _vk_call_with_token(
            "wall.get",
            {"owner_id": f"-{gid}", "count": 1},
            token,
        )
        can_post = True
    except Exception as exc:  # noqa: BLE001
        can_post = False
        wall_error = str(exc)

    # Для загрузки фото/видео обычно нужен именно USER-токен админа
    media_hint = ""
    if source == "env_community":
        media_hint = (
            " Сейчас работает токен сообщества — название группы читается. "
            "Для публикации картинок и видео лучше получить новый VK_USER_TOKEN "
            "(админ группы, права wall+photos+video+groups+offline) и вставить в канал."
        )
    if notes and source != "env_user":
        media_hint += " " + " | ".join(notes)

    return {
        "ok": True,
        "group_id": str(gid),
        "group_name": name,
        "screen_name": screen,
        "members_count": members,
        "source": source,
        "source_label": source_label,
        "can_read_wall": can_post,
        "wall_error": wall_error,
        "message": (
            f"Подключено: «{name}» (id {gid})"
            + (f", подписчиков: {members}" if members is not None else "")
            + f". Источник: {source_label}."
            + media_hint
        ),
        "notes": notes,
        "media_hint": media_hint.strip(),
    }


def _ssl_context():
    try:
        import certifi
        import ssl

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


def _friendly_vk_error(error: dict) -> str:
    code = error.get("error_code")
    msg = error.get("error_msg") or json.dumps(error, ensure_ascii=False)
    if code == 5 and "ip address" in msg.lower():
        return (
            "Токен привязан к другому IP (выдан с другого компьютера/сети). "
            "Получите новый токен пользователя с правом offline и вставьте его "
            "в настройки канала или в .env (VK_USER_TOKEN)."
        )
    if code == 5:
        return f"Токен ВК недействителен или отозван. Получите новый. Детали: {msg}"
    if code == 15:
        return f"Не хватает прав у токена (нужны wall, photos, video, groups). Детали: {msg}"
    if code == 100:
        return f"Неверный ID группы или параметры. Детали: {msg}"
    return f"VK API ошибка {code}: {msg}"


def _vk_call_with_token(method: str, params: dict, token: str) -> dict:
    api_version = os.environ.get("VK_API_VERSION", "5.199").strip() or "5.199"
    merged = {k: v for k, v in params.items() if v is not None and v != ""}
    merged["access_token"] = token
    merged["v"] = api_version
    encoded = parse.urlencode(merged).encode("utf-8")
    req = request.Request(
        f"https://api.vk.com/method/{method}",
        data=encoded,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    ctx = _ssl_context()
    with request.urlopen(req, timeout=120, context=ctx) as response:
        data = json.loads(response.read().decode("utf-8"))
    if "error" in data:
        raise RuntimeError(_friendly_vk_error(data["error"]))
    return data["response"]


def publish_draft(
    *,
    post_text: str,
    image_url: str = "",
    video_url: str = "",
    topic: str = "",
    user_token: str = "",
    user_group_id: str = "",
) -> dict:
    """Публикует пост с визуалом в сообщество."""
    token, group_id = _env_token_and_group(user_token, user_group_id)
    vk_message = prepare_post_text_for_vk(post_text)

    # Временно подставляем токен пользователя в окружение для функций upload_*
    prev_user = os.environ.get("VK_USER_TOKEN")
    os.environ["VK_USER_TOKEN"] = token
    try:
        draft = {
            "post_text": vk_message,
            "image_url": image_url or "",
            "video_url": video_url or "",
            "topic": topic or "",
            "output_files": {},
        }
        if not (image_url or video_url):
            # Текст без визуала — только если очень нужно для теста; правило проекта — с визуалом
            owner_id = f"-{group_id}"
            return _vk_call_with_token(
                "wall.post",
                {
                    "owner_id": owner_id,
                    "from_group": 1,
                    "message": vk_message,
                },
                token,
            )
        attachments = vk_pub.build_attachments_for_draft(draft, group_id)
        return vk_pub.publish_wall_post(group_id, vk_message, attachments)
    finally:
        if prev_user is None:
            os.environ.pop("VK_USER_TOKEN", None)
        else:
            os.environ["VK_USER_TOKEN"] = prev_user


def get_stats(
    *,
    user_token: str = "",
    user_group_id: str = "",
    posts_limit: int = 30,
    days: int = 7,
) -> dict:
    """
    Статистика канала для кабинета:
    - подписчики;
    - сумма лайков / комментариев / репостов / просмотров по последним постам;
    - топ постов;
    - по дням (stats.get), если токен позволяет.
    """
    from datetime import datetime

    token, group_id = _env_token_and_group(user_token, user_group_id)
    posts_limit = max(5, min(int(posts_limit or 30), 100))
    days = max(1, min(int(days or 7), 30))

    result: dict = {
        "group_id": group_id,
        "group_name": "",
        "members_count": None,
        "posts_limit": posts_limit,
        "posts_analyzed": 0,
        "likes": 0,
        "comments": 0,
        "reposts": 0,
        "views": 0,
        "avg_views": None,
        "avg_likes": None,
        "best_post": None,
        "top_by_views": [],
        "top_by_engagement": [],
        "recent_posts": [],
        "daily": [],
        "reach_today": None,
        "visitors_period": None,
        "views_period": None,
        "notes": [],
        "warnings": [],
    }

    # Название группы
    try:
        groups = _vk_call_with_token(
            "groups.getById",
            {"group_id": group_id, "fields": "members_count"},
            token,
        )
        if isinstance(groups, list) and groups:
            g0 = groups[0]
            result["group_name"] = (g0.get("name") or "").strip()
            if g0.get("members_count") is not None:
                result["members_count"] = g0.get("members_count")
    except Exception as exc:  # noqa: BLE001
        result["notes"].append(f"Название группы: {exc}")

    if result["members_count"] is None:
        try:
            members = _vk_call_with_token(
                "groups.getMembers",
                {"group_id": group_id, "count": 0},
                token,
            )
            result["members_count"] = members.get("count")
        except Exception as exc:  # noqa: BLE001
            result["warnings"].append(
                "Не удалось получить число подписчиков. Проверьте токен и ID группы."
            )
            result["notes"].append(f"Подписчики: {exc}")

    # Посты стены
    try:
        wall = _vk_call_with_token(
            "wall.get",
            {"owner_id": f"-{group_id}", "count": posts_limit, "filter": "owner"},
            token,
        )
        items = wall.get("items") or []
        posts: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            # пропускаем репосты чужих записей как «свои» метрики публикации
            if item.get("copy_history"):
                continue
            likes = int((item.get("likes") or {}).get("count") or 0)
            comments = int((item.get("comments") or {}).get("count") or 0)
            reposts = int((item.get("reposts") or {}).get("count") or 0)
            views = int((item.get("views") or {}).get("count") or 0)
            engagement = likes + comments + reposts
            text = (item.get("text") or "").replace("\n", " ").strip()
            if len(text) > 120:
                text = text[:117].rstrip() + "…"
            if not text:
                text = "(без текста — только визуал)"
            date_ts = int(item.get("date") or 0)
            date_label = (
                datetime.fromtimestamp(date_ts).strftime("%d.%m.%Y %H:%M")
                if date_ts
                else "—"
            )
            post_id = item.get("id")
            link = (
                f"https://vk.com/wall-{group_id}_{post_id}"
                if post_id is not None
                else ""
            )
            posts.append(
                {
                    "id": post_id,
                    "date": date_label,
                    "date_ts": date_ts,
                    "text": text,
                    "likes": likes,
                    "comments": comments,
                    "reposts": reposts,
                    "views": views,
                    "engagement": engagement,
                    "link": link,
                }
            )

        result["posts_analyzed"] = len(posts)
        result["likes"] = sum(p["likes"] for p in posts)
        result["comments"] = sum(p["comments"] for p in posts)
        result["reposts"] = sum(p["reposts"] for p in posts)
        result["views"] = sum(p["views"] for p in posts)
        if posts:
            result["avg_views"] = round(result["views"] / len(posts))
            result["avg_likes"] = round(result["likes"] / len(posts), 1)
            result["best_post"] = max(posts, key=lambda p: (p["views"], p["engagement"]))
            result["top_by_views"] = sorted(
                posts, key=lambda p: (p["views"], p["engagement"]), reverse=True
            )[:5]
            result["top_by_engagement"] = sorted(
                posts, key=lambda p: (p["engagement"], p["views"]), reverse=True
            )[:5]
            result["recent_posts"] = posts[:15]
        result["notes"].append(
            f"Метрики постов — по последним {len(posts)} записям со стены сообщества."
        )
    except Exception as exc:  # noqa: BLE001
        result["warnings"].append(
            "Не удалось прочитать стену. Нужен токен с доступом к стене группы."
        )
        result["notes"].append(f"Стена: {exc}")

    # Статистика сообщества по дням (часто нужен токен администратора)
    try:
        stats = _vk_call_with_token(
            "stats.get",
            {
                "group_id": group_id,
                "interval": "day",
                "intervals_count": days,
            },
            token,
        )
        daily: list[dict] = []
        views_sum = 0
        visitors_sum = 0
        if isinstance(stats, list):
            for day in stats:
                if not isinstance(day, dict):
                    continue
                visitors = day.get("visitors") or {}
                day_views = int(visitors.get("views") or 0)
                day_visitors = int(visitors.get("visitors") or 0)
                period_from = day.get("period_from") or day.get("day") or ""
                if isinstance(period_from, int):
                    label = datetime.fromtimestamp(period_from).strftime("%d.%m")
                else:
                    label = str(period_from)[-5:] if period_from else "—"
                daily.append(
                    {
                        "label": label,
                        "views": day_views,
                        "visitors": day_visitors,
                    }
                )
                views_sum += day_views
                visitors_sum += day_visitors
        result["daily"] = daily
        result["views_period"] = views_sum
        result["visitors_period"] = visitors_sum
        if daily:
            result["reach_today"] = daily[-1].get("views")
            result["notes"].append(
                f"Охват сообщества — stats.get за последние {len(daily)} дн."
            )
    except Exception as exc:  # noqa: BLE001
        result["warnings"].append(
            "Охват по дням недоступен с этим токеном "
            "(нужны права администратора сообщества на статистику). "
            "Цифры по постам выше всё равно считаются."
        )
        result["notes"].append(f"stats.get: {exc}")

    return result
