"""Проверки адресов, маскировка секретов в текстах ошибок, безопасный редирект."""
from __future__ import annotations

import ipaddress
import os
import re
import socket
from urllib.parse import urlparse

# Длинные куски, похожие на токен, и пары key=value из URL.
_QUERY_SECRET = re.compile(
    r"(?i)(access_token|refresh_token|client_secret|api_key|password|token)=([^&\s\"']+)"
)
_VK_TOKEN = re.compile(r"vk1\.[A-Za-z0-9._\-]{8,}")
_LONG_HEX = re.compile(r"\b[A-Za-z0-9_\-]{40,}\b")

_ENV_SECRET_NAMES = (
    "VK_USER_TOKEN",
    "VK_COMMUNITY_TOKEN",
    "VK_ADS_TOKEN",
    "VK_ADS_ACCESS_TOKEN",
    "VK_ADS_CLIENT_SECRET",
    "VK_ADS_REFRESH_TOKEN",
    "KIE_API_KEY",
    "VSEGPT_API_KEY",
    "APP_ENCRYPTION_KEY",
    "FLASK_SECRET_KEY",
    "SECRET_KEY",
    "ANTHROPIC_API_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
)


def scrub_secrets(text: str | None, *, limit: int = 500) -> str:
    """Убрать токены и ключи из текста, который попадёт в журнал, flash или JSON."""
    raw = text or ""
    if not raw:
        return ""
    cleaned = _QUERY_SECRET.sub(r"\1=***", raw)
    cleaned = _VK_TOKEN.sub("vk1.***", cleaned)
    for name in _ENV_SECRET_NAMES:
        value = (os.environ.get(name) or "").strip()
        if value and len(value) >= 8 and value in cleaned:
            cleaned = cleaned.replace(value, "***")
    if len(cleaned) > limit:
        cleaned = cleaned[:limit] + "…"
    return cleaned


def safe_next_url(candidate: str | None, fallback: str) -> str:
    """Разрешить только относительный путь этого сайта. Чужие адреса отбрасываются."""
    raw = (candidate or "").strip()
    if not raw or any(ch in raw for ch in "\r\n\t\\"):
        return fallback
    if not raw.startswith("/") or raw.startswith("//"):
        return fallback
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc:
        return fallback
    path = parsed.path or ""
    if not path.startswith("/") or path.startswith("//"):
        return fallback
    return raw


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def is_public_http_url(url: str | None) -> bool:
    """True только для http(s) на публичный адрес. Блокирует localhost и служебные сети."""
    raw = (url or "").strip()
    if not raw or len(raw) > 2000:
        return False
    try:
        parsed = urlparse(raw)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        return False
    if host in {"localhost", "metadata.google.internal", "metadata.google"} or host.endswith(
        ".local"
    ) or host.endswith(".internal"):
        return False
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        return _is_public_ip(literal)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if not _is_public_ip(ip):
            return False
    return True
