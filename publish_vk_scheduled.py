"""
Автопубликация черновиков VK из Supabase (текст + вложения одним постом).

Поддерживается:
  — одно или несколько фото (image_url + опционально output_files.image_urls / carousel_image_urls);
  — одно видео по HTTPS (video_url, например mp4 с KIE);
  — комбо фото + видео (например обложка + ролик).

Не реализовано (другие методы API): публикация VK Клипов (shortVideo.*), опросы, документы, аудио.
Для загрузки медиа на стену группы обычно нужен VK_USER_TOKEN администратора (scope: photos, wall, video, groups).
"""
import argparse
import json
import mimetypes
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib import parse, request


PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
ENV_FILE = PROJECT_ROOT / ".env"
VK_API_BASE = "https://api.vk.com/method/"
_DEFAULT_MAX_VIDEO = 450 * 1024 * 1024
_MAX_MEDIA_ATTACHMENTS = 10


def load_dotenv_file() -> None:
    if not ENV_FILE.exists():
        return

    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_required_env(name: str) -> str:
    load_dotenv_file()
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Не найдена переменная {name} в .env")
    return value


def get_vk_access_token() -> str:
    """
    Токен пользователя-админа (VK_USER_TOKEN) нужен для загрузки фото и видео на стену группы:
    методы photos.* и video.save с загрузкой файла недоступны или ограничены только токеном сообщества.
    """
    load_dotenv_file()
    user = os.environ.get("VK_USER_TOKEN", "").strip()
    if user:
        return user
    community = os.environ.get("VK_COMMUNITY_TOKEN", "").strip()
    if community:
        return community
    raise ValueError(
        "В .env нужен VK_USER_TOKEN (рекомендуется) или VK_COMMUNITY_TOKEN — хотя бы один из них."
    )


def _max_video_bytes() -> int:
    raw = os.environ.get("VK_MAX_VIDEO_UPLOAD_BYTES", "").strip()
    if raw.isdigit():
        return int(raw)
    return _DEFAULT_MAX_VIDEO


def supabase_request(method: str, path: str, *, query: str = "", payload: dict | None = None) -> dict | list:
    base = get_required_env("SUPABASE_URL").rstrip("/")
    key = get_required_env("SUPABASE_SERVICE_ROLE_KEY")
    url = f"{base}/rest/v1/{path}"
    if query:
        url = f"{url}?{query}"

    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = request.Request(
        url,
        data=body,
        method=method,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Prefer": "return=representation",
        },
    )

    with request.urlopen(req, timeout=60) as response:
        raw = response.read().decode("utf-8")
        if not raw:
            return {}
        return json.loads(raw)


def _vk_params_clean(params: dict) -> dict:
    return {k: v for k, v in params.items() if v is not None and v != ""}


def vk_api_call(method_name: str, params: dict) -> dict:
    token = get_vk_access_token()
    api_version = os.environ.get("VK_API_VERSION", "5.199").strip() or "5.199"

    merged = _vk_params_clean(dict(params))
    merged["access_token"] = token
    merged["v"] = api_version
    encoded = parse.urlencode(merged).encode("utf-8")
    req = request.Request(
        f"{VK_API_BASE}{method_name}",
        data=encoded,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    with request.urlopen(req, timeout=120) as response:
        data = json.loads(response.read().decode("utf-8"))

    if "error" in data:
        raise RuntimeError(f"VK API {method_name}: {json.dumps(data['error'], ensure_ascii=False)}")
    return data["response"]


def download_binary(url: str, *, timeout: int = 180) -> tuple[bytes, str]:
    req = request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with request.urlopen(req, timeout=timeout) as response:
        content = response.read()
        content_type = response.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
    return content, content_type


def download_binary_limited(url: str, *, max_bytes: int, timeout: int = 900) -> tuple[bytes, str]:
    req = request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    chunks: list[bytes] = []
    total = 0
    with request.urlopen(req, timeout=timeout) as response:
        ctype = response.headers.get("Content-Type", "application/octet-stream").split(";")[0].strip()
        while True:
            part = response.read(1024 * 512)
            if not part:
                break
            total += len(part)
            if total > max_bytes:
                raise RuntimeError(
                    f"Файл по URL больше лимита {max_bytes} байт (задаётся VK_MAX_VIDEO_UPLOAD_BYTES)."
                )
            chunks.append(part)
    return b"".join(chunks), ctype


def upload_photo_bytes(content: bytes, content_type: str, group_id: str) -> str:
    """Залить уже скачанные байты картинки на стену сообщества."""
    upload_server = vk_api_call("photos.getWallUploadServer", {"group_id": group_id})
    upload_url = upload_server["upload_url"]
    extension = mimetypes.guess_extension(content_type or "") or ".jpg"
    filename = f"vk-image{extension}"

    boundary = f"----CursorBoundary{uuid.uuid4().hex}"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="photo"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    body = head + content + tail

    req = request.Request(
        upload_url,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with request.urlopen(req, timeout=240) as response:
        upload_result = json.loads(response.read().decode("utf-8"))

    saved = vk_api_call(
        "photos.saveWallPhoto",
        {
            "group_id": group_id,
            "photo": upload_result["photo"],
            "server": upload_result["server"],
            "hash": upload_result["hash"],
        },
    )
    photo = saved[0]
    return f"photo{photo['owner_id']}_{photo['id']}"


def upload_photo_to_vk(image_url: str, group_id: str) -> str:
    content, content_type = download_binary(image_url, timeout=240)
    return upload_photo_bytes(content, content_type, group_id)


def upload_video_to_vk(video_url: str, group_id: str, title: str) -> str:
    """
    Загрузка видеофайла по HTTPS (например, mp4 с KIE) в видеозапись сообщества и строка вложения video{owner_id}_{id}.
    Цепочка: video.save → POST на upload_url с полем video_file (как у официального upload flow).
    """
    max_b = _max_video_bytes()
    content, content_type = download_binary_limited(video_url, max_bytes=max_b, timeout=900)
    ext = mimetypes.guess_extension(content_type) or ".mp4"
    if ext.lower() not in (".mp4", ".webm", ".mov", ".mpeg", ".m4v"):
        ext = ".mp4"
    filename = f"vk-video{ext}"

    safe_title = (title or "video").strip()[:128] or "video"
    save_resp = vk_api_call(
        "video.save",
        {
            "group_id": group_id,
            "name": safe_title,
            "wallpost": 0,
        },
    )
    upload_url = save_resp["upload_url"]

    boundary = f"----CursorBoundary{uuid.uuid4().hex}"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="video_file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type or 'video/mp4'}\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    body = head + content + tail

    req = request.Request(
        upload_url,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with request.urlopen(req, timeout=900) as response:
        raw_upload = response.read().decode("utf-8")
        upload_result = json.loads(raw_upload) if raw_upload else {}

    owner_id = upload_result.get("owner_id", save_resp.get("owner_id"))
    video_id = upload_result.get("video_id", save_resp.get("video_id"))
    if video_id is None or owner_id is None:
        raise RuntimeError(
            "Не удалось получить owner_id/video_id после загрузки видео. "
            f"Ответ: {raw_upload[:500] if raw_upload else upload_result}"
        )
    return f"video{owner_id}_{video_id}"


def collect_image_urls_for_post(draft: dict, *, reserve_slots_for_video: int) -> list[str]:
    """
    Собирает URL картинок: image_url + списки из output_files (carousel).
    reserve_slots_for_video — сколько мест оставить под видео в лимите _MAX_MEDIA_ATTACHMENTS.
    """
    limit = max(0, _MAX_MEDIA_ATTACHMENTS - reserve_slots_for_video)
    seen: set[str] = set()
    out: list[str] = []
    candidates: list[str] = []

    main = (draft.get("image_url") or "").strip()
    if main:
        candidates.append(main)

    of = draft.get("output_files") or {}
    if isinstance(of, dict):
        for key in ("image_urls", "carousel_image_urls", "extra_image_urls"):
            val = of.get(key)
            if isinstance(val, list):
                for x in val:
                    s = str(x).strip()
                    if s.startswith("http"):
                        candidates.append(s)
            elif isinstance(val, str) and val.strip().startswith("http"):
                candidates.append(val.strip())

    for url in candidates:
        if url not in seen:
            seen.add(url)
            out.append(url)
        if len(out) >= limit:
            break
    return out


def build_attachments_for_draft(draft: dict, group_id: str) -> str:
    """
    Форматы:
    - только фото (одно или несколько);
    - только видео;
    - фото + видео (типичный image_to_video: обложка + ролик).
    Порядок: сначала все фото, затем видео — единый пост wall.post.
    """
    post_text = (draft.get("post_text") or "").strip()
    video_url = (draft.get("video_url") or "").strip()
    topic = (draft.get("topic") or "").strip()
    title_for_video = topic or (post_text[:80] if post_text else "video")

    has_video = bool(video_url)
    image_urls = collect_image_urls_for_post(draft, reserve_slots_for_video=1 if has_video else 0)

    if not image_urls and not has_video:
        raise ValueError("Нет ни image_url (и карусели в output_files), ни video_url — нечего прикрепить.")

    parts: list[str] = []
    for url in image_urls:
        parts.append(upload_photo_to_vk(url, group_id))
    if has_video:
        parts.append(upload_video_to_vk(video_url, group_id, title_for_video))

    if not parts:
        raise ValueError("Пустой список вложений после обработки URL.")
    return ",".join(parts)


def publish_wall_post(group_id: str, message: str, attachments: str) -> dict:
    owner_id = f"-{group_id}"
    return vk_api_call(
        "wall.post",
        {
            "owner_id": owner_id,
            "from_group": 1,
            "message": message,
            "attachments": attachments,
        },
    )


def update_vk_draft(draft_id: str, payload: dict) -> None:
    quoted_id = parse.quote(f"eq.{draft_id}", safe="=.")
    supabase_request("PATCH", "vk_drafts", query=f"id={quoted_id}", payload=payload)


def get_due_vk_drafts(limit: int = 20) -> list[dict]:
    now_iso = datetime.now(timezone.utc).isoformat()
    query = (
        "select=id,topic,post_type,post_text,visual_type,image_url,video_url,output_files,notes,scheduled_for,status"
        "&status=eq.ready"
        "&publish_channel=eq.vk"
        f"&scheduled_for=lte.{parse.quote(now_iso, safe='')}"
        "&order=scheduled_for.asc"
        f"&limit={limit}"
    )
    data = supabase_request("GET", "vk_drafts", query=query)
    if not isinstance(data, list):
        return []
    return data


def mark_publish_problem(draft: dict, message: str) -> None:
    update_vk_draft(
        draft["id"],
        {
            "status": "draft",
            "notes": message,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def draft_preview(draft: dict) -> str:
    text = (draft.get("post_text") or "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) > 120:
        text = f"{text[:120]}..."
    media = []
    if (draft.get("image_url") or "").strip():
        media.append("image")
    if (draft.get("video_url") or "").strip():
        media.append("video")
    return (
        f"id={draft.get('id')} | scheduled_for={draft.get('scheduled_for')} | "
        f"topic={draft.get('topic') or '-'} | media={'+'.join(media) or 'нет'} | text={text or '-'}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Публикация VK-черновиков из Supabase по расписанию.")
    parser.add_argument("--dry-run", action="store_true", help="Только показать due-черновики, ничего не публиковать.")
    parser.add_argument("--limit", type=int, default=20, help="Сколько due-черновиков обработать за запуск.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        group_id = get_required_env("VK_GROUP_ID")
        get_vk_access_token()
    except Exception as exc:  # noqa: BLE001
        print(f"Ошибка настроек VK: {exc}", file=sys.stderr)
        return 1

    try:
        drafts = get_due_vk_drafts(limit=args.limit)
    except Exception as exc:  # noqa: BLE001
        print(f"Ошибка чтения черновиков из Supabase: {exc}", file=sys.stderr)
        return 1

    if not drafts:
        print("Нет готовых черновиков для публикации.")
        return 0

    if args.dry_run:
        print("Готовые черновики к публикации, без запуска VK API:")
        for draft in drafts:
            print("-", draft_preview(draft))
        return 0

    published_count = 0
    for draft in drafts:
        draft_id = draft["id"]
        post_text = (draft.get("post_text") or "").strip()

        if not post_text:
            mark_publish_problem(draft, "Автопубликация остановлена: пустой текст поста.")
            print(f"{draft_id}: пропуск, пустой текст.")
            continue

        try:
            from webapp.services.post_format import prepare_post_text_for_vk

            vk_message = prepare_post_text_for_vk(post_text)
            attachments = build_attachments_for_draft(draft, group_id)
            post_result = publish_wall_post(group_id, vk_message, attachments)
            post_id = post_result["post_id"]
            post_url = f"https://vk.com/wall-{group_id}_{post_id}"

            output_files = draft.get("output_files") or {}
            if not isinstance(output_files, dict):
                output_files = {}
            output_files["vk_post_url"] = post_url
            output_files["vk_attachments"] = attachments

            update_vk_draft(
                draft_id,
                {
                    "status": "published",
                    "published_at": datetime.now(timezone.utc).isoformat(),
                    "notes": None,
                    "output_files": output_files,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            print(f"{draft_id}: опубликовано -> {post_url}")
            published_count += 1
        except Exception as exc:  # noqa: BLE001
            mark_publish_problem(draft, f"Ошибка автопубликации в VK: {exc}")
            print(f"{draft_id}: ошибка публикации -> {exc}", file=sys.stderr)

    print(f"Готово. Опубликовано: {published_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
