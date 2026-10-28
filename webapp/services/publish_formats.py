"""Форматы публикации в ВК: код в базе и подпись в интерфейсе.

Текст поста при смене формата не стирается. Меняются только флаги,
что прикреплять при публикации: ничего, картинку, карусель или видео.
"""
from __future__ import annotations

import json

# code, подпись в интерфейсе
CHOICES: tuple[tuple[str, str], ...] = (
    ("text", "Только текст"),
    ("image", "Текст + картинка"),
    ("carousel", "Карусель"),
    ("clip", "Клип / видео"),
    ("animation", "Видео-анимация"),
)

_CODES = {code for code, _label in CHOICES}


def choices() -> list[dict[str, str]]:
    return [{"code": code, "label": label} for code, label in CHOICES]


def label(raw: str | None) -> str:
    code = normalize_format(raw)
    for item, title in CHOICES:
        if item == code:
            return title
    return "Текст + картинка"


def normalize_format(raw: str | None) -> str:
    """Свободная строка от ИИ или код из списка → один из кодов."""
    text = (raw or "").strip().lower().replace("ё", "е")
    if text in _CODES:
        return text
    if not text:
        return "image"
    if any(word in text for word in ("анимац", "animation", "veo")):
        return "animation"
    if any(word in text for word in ("карусел", "carousel", "слайд")):
        return "carousel"
    if any(word in text for word in ("клип", "clip", "рилс", "reels")):
        return "clip"
    if "видео" in text or text == "video":
        return "clip"
    if any(word in text for word in ("только текст", "text only", "без картин", "без фото")):
        return "text"
    if text in {"text", "текст"} or (
        "текст" in text and "картин" not in text and "фото" not in text
    ):
        return "text"
    if any(word in text for word in ("картин", "фото", "image", "инфограф")):
        return "image"
    return "image"


def media_flags(code: str | None) -> tuple[bool, bool]:
    """Что прикреплять к посту: (картинка, видео)."""
    kind = normalize_format(code)
    if kind == "text":
        return False, False
    if kind in {"image", "carousel"}:
        return True, False
    if kind in {"clip", "animation"}:
        return False, True
    return True, False


def needs_video(code: str | None) -> bool:
    return normalize_format(code) in {"clip", "animation"}


def apply_to_draft(draft, raw: str | None) -> str:
    """Записать формат. Текст поста и уже готовые файлы не удаляются."""
    code = normalize_format(raw)
    draft.publish_format = code
    image, video = media_flags(code)
    draft.publish_with_image = image
    draft.publish_with_video = video
    return code


def carousel_urls(draft) -> list[str]:
    raw = getattr(draft, "carousel_urls_json", None) or "[]"
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out: list[str] = []
    for item in data:
        url = str(item or "").strip()
        if url and url not in out:
            out.append(url)
    return out[:8]


def set_carousel_urls(draft, urls: list[str]) -> None:
    clean: list[str] = []
    for item in urls:
        url = str(item or "").strip()
        if url and url not in clean:
            clean.append(url)
    draft.carousel_urls_json = json.dumps(clean[:8], ensure_ascii=False)
