"""Настройки веб-приложения SMM для интенсивов."""
from pathlib import Path
import os
import secrets

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _session_secret() -> str:
    configured = os.environ.get("FLASK_SECRET_KEY") or os.environ.get("SECRET_KEY")
    if configured:
        return configured
    key_path = PROJECT_ROOT / "webapp" / ".secret_key"
    if key_path.is_file():
        return key_path.read_text(encoding="utf-8").strip()
    generated = secrets.token_urlsafe(48)
    key_path.write_text(generated, encoding="utf-8")
    return generated


class Config:
    SECRET_KEY = _session_secret()
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{PROJECT_ROOT / 'webapp' / 'site.db'}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = PROJECT_ROOT / "webapp" / "uploads"
    MAX_CONTENT_LENGTH = 64 * 1024 * 1024  # 64 МБ (несколько фото с телефона)
    # Модели по умолчанию (KIE)
    DEFAULT_IMAGE_MODEL = "gpt-image-2-text-to-image"
    DEFAULT_VIDEO_PROVIDER = "kling"
