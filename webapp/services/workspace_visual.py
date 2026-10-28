"""Визуальный стиль канала: промпт и референсные картинки."""
from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import run_agent as agent  # noqa: E402

if TYPE_CHECKING:
    from webapp.models import Workspace

REF_ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_REFERENCES = 8
MAX_REFERENCES_FOR_AI = 4
# Референсы с телефона часто 8–20 МБ — сжимаем до разумного размера для API
REF_MAX_SIDE_PX = 2048
REF_JPEG_QUALITY = 88
MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def save_uploaded_reference(file_storage, dest_path: Path) -> Path:
    """
    Сохраняет референс на диск. Крупные фото уменьшает (длинная сторона ≤ 2048 px)
    и сохраняет как JPEG, чтобы не упираться в лимит загрузки.
    GIF не трогаем (анимация). Возвращает итоговый путь (может сменить расширение).
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    ext = dest_path.suffix.lower()
    raw = file_storage.read()
    if not raw:
        raise ValueError("Пустой файл.")

    # GIF оставляем как есть
    if ext == ".gif" or raw[:6] in (b"GIF87a", b"GIF89a"):
        dest_path.write_bytes(raw)
        return dest_path

    try:
        from io import BytesIO

        from PIL import Image

        img = Image.open(BytesIO(raw))
        img.load()
        # Прозрачность → RGB на белом
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.split()[-1])
            img = background
        else:
            img = img.convert("RGB")

        w, h = img.size
        longest = max(w, h)
        if longest > REF_MAX_SIDE_PX:
            scale = REF_MAX_SIDE_PX / float(longest)
            img = img.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))),
                Image.Resampling.LANCZOS,
            )

        out_path = dest_path.with_suffix(".jpg")
        img.save(out_path, format="JPEG", quality=REF_JPEG_QUALITY, optimize=True)
        return out_path
    except Exception:
        # Если Pillow не смог — сохраняем оригинал
        dest_path.write_bytes(raw)
        return dest_path



def detect_image_media_type(file_path: Path) -> str | None:
    """Определяет MIME по содержимому файла, а не только по расширению."""
    try:
        header = file_path.read_bytes()[:16]
    except OSError:
        return None
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "image/webp"
    return MIME_BY_EXT.get(file_path.suffix.lower())


def load_reference_images(workspace: Workspace) -> list[dict]:
    raw = (getattr(workspace, "reference_images_json", None) or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict) and item.get("path")]


def save_reference_images(workspace: Workspace, items: list[dict]) -> None:
    workspace.reference_images_json = json.dumps(items[:MAX_REFERENCES], ensure_ascii=False)


def reference_upload_dir(upload_root: Path, user_id: int, workspace_id: int) -> Path:
    path = upload_root / str(user_id) / "workspace" / str(workspace_id) / "refs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def add_reference_image(
    workspace: Workspace,
    *,
    name: str,
    relative_path: str,
) -> dict:
    items = load_reference_images(workspace)
    if len(items) >= MAX_REFERENCES:
        raise ValueError(f"Можно сохранить не больше {MAX_REFERENCES} референсов на канал.")
    item = {
        "id": f"ref_{int(time.time() * 1000)}",
        "name": name,
        "path": relative_path,
    }
    items.append(item)
    save_reference_images(workspace, items)
    return item


def remove_reference_image(workspace: Workspace, ref_id: str) -> dict | None:
    items = load_reference_images(workspace)
    removed = None
    kept: list[dict] = []
    for item in items:
        if item.get("id") == ref_id and removed is None:
            removed = item
        else:
            kept.append(item)
    if removed:
        save_reference_images(workspace, kept)
    return removed


def build_media_urls(user_id: int, refs: list[dict]) -> list[str]:
    """Публичные URL загруженных референсов (для KIE и промпта)."""
    from flask import url_for

    urls: list[str] = []
    for ref in refs[:MAX_REFERENCES]:
        rel = (ref.get("path") or "").strip()
        if not rel:
            continue
        urls.append(url_for("smm.media_file", user_id=user_id, filename=rel, _external=True))
    return urls


def reference_names_summary(refs: list[dict]) -> str:
    names = [(r.get("name") or "референс").strip() for r in refs[:MAX_REFERENCES]]
    return ", ".join(n for n in names if n)


def load_reference_images_b64(
    upload_root: Path,
    user_id: int,
    refs: list[dict],
    *,
    max_count: int = MAX_REFERENCES_FOR_AI,
) -> list[dict]:
    """Читает референсы с диска для vision-запроса к Claude."""
    out: list[dict] = []
    for ref in refs[:max_count]:
        rel = (ref.get("path") or "").strip()
        if not rel:
            continue
        file_path = upload_root / str(user_id) / rel
        if not file_path.is_file():
            continue
        media_type = detect_image_media_type(file_path)
        if not media_type:
            continue
        out.append(
            {
                "name": (ref.get("name") or file_path.name).strip(),
                "media_type": media_type,
                "data_b64": base64.standard_b64encode(file_path.read_bytes()).decode("ascii"),
            }
        )
    return out


def resolve_reference_local_files(
    upload_root: Path,
    user_id: int,
    refs: list[dict],
    *,
    max_count: int = MAX_REFERENCES,
) -> list[dict]:
    """
    Локальные пути референсов для generation (не путать с vision base64).
    Элемент: {name, path, media_type} — path абсолютный на диске.
    """
    out: list[dict] = []
    for ref in refs[:max_count]:
        rel = (ref.get("path") or "").strip()
        if not rel:
            continue
        file_path = (upload_root / str(user_id) / rel).resolve()
        if not file_path.is_file():
            continue
        media_type = detect_image_media_type(file_path) or "image/jpeg"
        out.append(
            {
                "name": (ref.get("name") or file_path.name).strip(),
                "path": str(file_path),
                "media_type": media_type,
            }
        )
    return out


def build_style_preview_prompt(
    *,
    name: str,
    theme: str = "",
    description: str = "",
    visual_style_prompt: str = "",
    brand_site: str = "",
) -> str:
    """Промпт для тестовой картинки стиля канала (не привязан к посту)."""
    footer = (brand_site or "").strip()
    footer_line = (
        f"Подпись внизу по центру маленьким текстом: «{footer}».\n"
        if footer
        else "Подпись внизу не добавлять.\n"
    )
    # Стрелки →← в описании стиля («было → стало») — не надписи в кадре;
    # для image-промпта заменяем на графическое описание.
    style_clean = agent.sanitize_visual_prompt_symbols(
        (visual_style_prompt or "").strip()
        or "аккуратная инфографика, светлый фон, крупная кириллица"
    )
    return (
        "Тестовая инфографика для проверки фирменного стиля VK-канала.\n"
        "Это не пост — покажи типичный визуальный кадр канала.\n\n"
        f"Канал: {name or 'канал'}\n"
        f"Тематика: {theme or 'не указана'}\n"
        f"Описание: {description or 'не указано'}\n\n"
        "Обязательный стиль канала:\n"
        f"{style_clean}\n\n"
        "Композиция примера:\n"
        "1. Заголовок вверху: «Пример оформления канала»\n"
        "2. Одна короткая строка по центру: «Так будут выглядеть ваши посты»\n"
        "3. Можно показать переход «было» и «стало» через нарисованную стрелку-линию "
        "(не символ в тексте, а графический элемент)\n"
        "4. Минимум элементов, без лишнего текста\n\n"
        f"{footer_line}"
        "Формат 4:5. Все смысловые надписи только кириллицей, каждую фразу в «ёлочках». "
        "Крупный рубленый шрифт, высокий контраст, без латиницы в надписях."
    )


def generate_style_preview_image(
    *,
    name: str,
    theme: str = "",
    description: str = "",
    visual_style_prompt: str = "",
    brand_site: str = "",
    reference_image_urls: list[str] | None = None,
    reference_local_files: list[dict] | None = None,
    reference_image_names: list[str] | None = None,
    on_progress=None,
) -> str:
    style = (visual_style_prompt or "").strip()
    if len(style) < 10:
        raise ValueError(
            "Сначала заполните промпт визуального стиля (минимум 10 символов) "
            "или сгенерируйте его кнопкой «ИИ генерация»."
        )
    if len((name or "").strip()) < 2:
        raise ValueError("Укажите название канала.")

    if on_progress:
        try:
            on_progress("visual_prepare", "Генерация примера стиля…")
        except Exception:
            pass

    prompt_text = build_style_preview_prompt(
        name=name.strip(),
        theme=theme.strip(),
        description=description.strip(),
        visual_style_prompt=style,
        brand_site=brand_site.strip(),
    )
    local_files = list(reference_local_files or [])
    has_refs = bool(local_files) or bool(
        agent.filter_public_reference_urls(reference_image_urls)
    )
    prompt_text = agent.append_real_photo_reference_rule(
        prompt_text, has_references=has_refs
    )
    image_vd = {
        "prompt_text": prompt_text,
        "aspect_ratio": "4:5",
        "resolution": "1K",
        "output_format": "png",
    }
    image_vd, vreport = agent.validate_and_prepare_image_visual_data(
        image_vd, brand_footer=brand_site.strip()
    )
    if not vreport.get("is_safe"):
        raise ValueError(
            "Промпт примера не прошёл проверку: "
            + "; ".join(vreport.get("errors") or ["неизвестная ошибка"])
        )

    if on_progress:
        try:
            on_progress("image_gpt_image_2", "Идёт генерация примера…")
        except Exception:
            pass

    kie_key = agent.get_api_key()
    try:
        image_url, provider_label = agent.generate_image_url_with_fallback(
            image_vd,
            reference_image_urls=reference_image_urls,
            reference_local_files=local_files,
            reference_image_names=reference_image_names,
            kie_key=kie_key,
            allow_no_person_fallback=True,
        )
    except RuntimeError as exc:
        raise RuntimeError(str(exc)) from exc
    if provider_label != agent.KIE_IMAGE_MODEL_LABEL:
        pass  # пример стиля — без предупреждения в UI
    return image_url

