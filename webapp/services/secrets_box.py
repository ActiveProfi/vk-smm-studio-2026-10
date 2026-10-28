"""Шифрование чувствительных строк в БД (токены ВК / Ads).

Формат: enc:<fernet_token>
Старые значения без префикса читаются как есть (миграция на лету при сохранении).
Ключ: APP_ENCRYPTION_KEY или FLASK_SECRET_KEY / SECRET_KEY.
"""
from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

ENC_PREFIX = "enc:"


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    raw = (
        (os.environ.get("APP_ENCRYPTION_KEY") or "").strip()
        or (os.environ.get("FLASK_SECRET_KEY") or "").strip()
        or (os.environ.get("SECRET_KEY") or "").strip()
        or "change-me-in-production-nds04ka-vk"
    )
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal(plain: str | None) -> str:
    """Зашифровать строку для хранения в БД."""
    text = (plain or "").strip()
    if not text:
        return ""
    if text.startswith(ENC_PREFIX):
        return text
    token = _fernet().encrypt(text.encode("utf-8")).decode("ascii")
    return ENC_PREFIX + token


def reveal(stored: str | None) -> str:
    """Расшифровать значение из БД (или вернуть plaintext legacy)."""
    text = (stored or "").strip()
    if not text:
        return ""
    if not text.startswith(ENC_PREFIX):
        return text
    blob = text[len(ENC_PREFIX) :]
    try:
        return _fernet().decrypt(blob.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        return ""


def is_sealed(stored: str | None) -> bool:
    return (stored or "").strip().startswith(ENC_PREFIX)


def mask(stored_or_plain: str | None, keep: int = 4) -> str:
    """Маска для UI: не светить секрет целиком."""
    plain = reveal(stored_or_plain) if is_sealed(stored_or_plain) else (stored_or_plain or "")
    plain = plain.strip()
    if not plain:
        return ""
    if len(plain) <= keep * 2:
        return "***"
    return plain[:keep] + "…" + "***" + "…" + plain[-keep:]
