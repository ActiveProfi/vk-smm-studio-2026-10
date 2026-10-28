"""Настройки веб-приложения SMM для интенсивов."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Config:
    SECRET_KEY = "change-me-in-production-nds04ka-vk"
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{PROJECT_ROOT / 'webapp' / 'site.db'}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = PROJECT_ROOT / "webapp" / "uploads"
    MAX_CONTENT_LENGTH = 64 * 1024 * 1024  # 64 МБ (несколько фото с телефона)
    # Модели по умолчанию (KIE)
    DEFAULT_IMAGE_MODEL = "gpt-image-2-text-to-image"
    DEFAULT_VIDEO_PROVIDER = "kling"
