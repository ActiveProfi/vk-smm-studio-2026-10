"""Короткий латинский код из русского названия (для рубрик канала)."""
from __future__ import annotations

import re

_TRANSLIT = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def slugify_code(text: str, *, max_len: int = 48) -> str:
    """«Экспертный пост» → expertnyy_post; пустое → rubric."""
    raw = (text or "").strip().lower()
    if not raw:
        return "rubric"
    chars: list[str] = []
    for ch in raw:
        if ch in _TRANSLIT:
            chars.append(_TRANSLIT[ch])
        elif "a" <= ch <= "z" or "0" <= ch <= "9":
            chars.append(ch)
        elif ch in {" ", "-", "_", ".", "/", "\\", ",", ";"}:
            chars.append("_")
        # остальное пропускаем
    slug = re.sub(r"_+", "_", "".join(chars)).strip("_")
    if not slug:
        slug = "rubric"
    if slug[0].isdigit():
        slug = "r_" + slug
    return slug[:max_len].rstrip("_") or "rubric"


def unique_rubric_code(
    title: str,
    *,
    existing_codes: set[str] | list[str],
    preferred: str | None = None,
    exclude: str | None = None,
) -> str:
    """Уникальный код в рамках канала."""
    taken = {str(c).strip().lower() for c in existing_codes if str(c).strip()}
    if exclude:
        taken.discard(exclude.strip().lower())

    base = slugify_code(preferred or title)
    if base not in taken:
        return base
    for i in range(2, 100):
        candidate = f"{base[:40]}_{i}"
        if candidate not in taken:
            return candidate
    return f"{base[:40]}_{len(taken) + 1}"
