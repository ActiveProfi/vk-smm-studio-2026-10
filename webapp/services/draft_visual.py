"""Выбор визуала черновика: что показывать и что публиковать в VK."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from webapp.models import Draft


def default_publish_flags(draft: Draft) -> tuple[bool, bool]:
    """Разумные галочки по умолчанию, если в БД ещё не сохранены."""
    has_image = bool((draft.image_url or "").strip())
    has_video = bool((draft.video_url or "").strip())
    if has_image and has_video:
        return True, False
    if has_image:
        return True, False
    if has_video:
        return False, True
    return True, False


def get_publish_flags(draft: Draft) -> tuple[bool, bool]:
    fmt = (getattr(draft, "publish_format", None) or "").strip()
    if fmt:
        from webapp.services.publish_formats import media_flags, normalize_format

        code = normalize_format(fmt)
        if code == "text":
            return False, False
        want_image, want_video = media_flags(code)
        has_image = bool((draft.image_url or "").strip())
        has_video = bool((draft.video_url or "").strip())
        return want_image and has_image, want_video and has_video

    has_image = bool((draft.image_url or "").strip())
    has_video = bool((draft.video_url or "").strip())
    if not has_image and not has_video:
        return False, False

    pub_image = bool(getattr(draft, "publish_with_image", True))
    pub_video = bool(getattr(draft, "publish_with_video", False))

    if pub_image and not has_image:
        pub_image = False
    if pub_video and not has_video:
        pub_video = False

    if has_image or has_video:
        if not pub_image and not pub_video:
            pub_image, pub_video = default_publish_flags(draft)
    return pub_image, pub_video


def apply_generation_flags(draft: Draft, *, generate_image: bool, generate_video: bool) -> None:
    """После генерации/перегенерации — что публиковать и убрать лишние файлы."""
    if generate_image and not generate_video:
        draft.video_url = ""
        draft.publish_with_image = True
        draft.publish_with_video = False
    elif generate_video and not generate_image:
        draft.image_url = ""
        draft.publish_with_image = False
        draft.publish_with_video = True
    elif generate_image and generate_video:
        draft.publish_with_image = True
        draft.publish_with_video = True


def apply_pipeline_urls(
    draft: Draft,
    pipeline: dict,
    *,
    generate_image: bool,
    generate_video: bool,
    preserve_image: bool = False,
) -> None:
    """Записать URL из pipeline с учётом выбранного типа визуала."""
    if generate_image and pipeline.get("image_url"):
        draft.image_url = pipeline["image_url"]
    if generate_video and pipeline.get("video_url"):
        draft.video_url = pipeline["video_url"]
    if preserve_image:
        return
    apply_generation_flags(draft, generate_image=generate_image, generate_video=generate_video)


def resolve_publish_media(draft: Draft) -> tuple[str, str]:
    """URL для wall.post — только отмеченные галочками типы."""
    pub_image, pub_video = get_publish_flags(draft)
    image_url = (draft.image_url or "").strip() if pub_image else ""
    video_url = (draft.video_url or "").strip() if pub_video else ""
    return image_url, video_url


def set_publish_flags(draft: Draft, *, publish_with_image: bool, publish_with_video: bool) -> None:
    has_image = bool((draft.image_url or "").strip())
    has_video = bool((draft.video_url or "").strip())
    draft.publish_with_image = bool(publish_with_image and has_image)
    draft.publish_with_video = bool(publish_with_video and has_video)
    if (has_image or has_video) and not draft.publish_with_image and not draft.publish_with_video:
        draft.publish_with_image, draft.publish_with_video = default_publish_flags(draft)
