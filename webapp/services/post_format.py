"""Форматирование текста поста VK для предпросмотра и публикации."""
from __future__ import annotations

import html
import re


def _apply_bold_markup(line: str) -> str:
    return re.sub(
        r"\*\*(.+?)\*\*",
        lambda m: f"<strong>{html.escape(m.group(1))}</strong>",
        html.escape(line),
    )


def render_vk_post_html(post_text: str) -> str:
    """Показать пост в предпросмотре: заголовок крупнее, подзаголовки жирные."""
    if not (post_text or "").strip():
        return ""

    blocks: list[str] = []
    title_done = False

    for raw_line in post_text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            blocks.append('<div class="post-gap"></div>')
            continue

        formatted = _apply_bold_markup(line)
        has_bold = "<strong>" in formatted

        if not title_done and has_bold:
            blocks.append(f'<div class="post-title">{formatted}</div>')
            title_done = True
            continue

        if has_bold:
            blocks.append(f'<div class="post-subtitle">{formatted}</div>')
            continue

        blocks.append(f'<p class="post-paragraph">{formatted}</p>')

    return "\n".join(blocks)


def to_vk_unicode_bold(text: str) -> str:
    """
    Жирный текст для ленты VK через Unicode (API wall.post не понимает **).
    Поддержка кириллицы и латиницы.
    """
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        if 0x41 <= code <= 0x5A:
            out.append(chr(0x1D400 + code - 0x41))
        elif 0x61 <= code <= 0x7A:
            out.append(chr(0x1D41A + code - 0x61))
        elif 0x410 <= code <= 0x42F:
            out.append(chr(0x1D670 + code - 0x410))
        elif 0x430 <= code <= 0x44F:
            out.append(chr(0x1D68A + code - 0x430))
        elif ch == "Ё":
            out.append("\U0001D681")
        elif ch == "ё":
            out.append("\U0001D69B")
        else:
            out.append(ch)
    return "".join(out)


def prepare_post_text_for_vk(post_text: str) -> str:
    """
    Текст для wall.post: убираем **...**, оставляем обычную кириллицу.

    VK API не поддерживает markdown и HTML в message.
    Unicode «жирный» (Mathematical Alphanumeric Symbols) в ленте VK
    часто отображается квадратиками — поэтому публикуем plain text.
    В предпросмотре кабинета жирность по-прежнему через render_vk_post_html().
    """
    return strip_vk_bold_markers(post_text)


def strip_vk_bold_markers(post_text: str) -> str:
    """Убрать ** без замены на жирный (запасной вариант)."""
    return re.sub(r"\*\*(.+?)\*\*", r"\1", post_text or "")
