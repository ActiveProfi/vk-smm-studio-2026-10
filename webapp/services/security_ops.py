"""Безопасность: лимит входа, журнал действий, баннер DEV_SKIP.

Полный IP-адрес не хранится: в журнале укороченная запись, для лимита — хэш.
Журнал показывается только своему агентству.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta

from flask import request
from flask_login import current_user

from webapp.models import SecurityEvent, User, db
from webapp.services.http_guard import scrub_secrets

LOGIN_WINDOW_MIN = 15
LOGIN_MAX_FAILS = 7
REGISTER_WINDOW_MIN = 60
REGISTER_MAX = 8
PORTAL_WINDOW_MIN = 10
PORTAL_MAX = 20


def _trust_proxy() -> bool:
    return (os.environ.get("TRUST_PROXY") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def client_ip() -> str:
    """Адрес клиента. Заголовок X-Forwarded-For учитываем только если TRUST_PROXY=1."""
    if _trust_proxy():
        forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        if forwarded:
            return forwarded[:64]
    return (request.remote_addr or "")[:64]


def _hash_key() -> str:
    return (
        (os.environ.get("APP_ENCRYPTION_KEY") or "").strip()
        or (os.environ.get("FLASK_SECRET_KEY") or "").strip()
        or (os.environ.get("SECRET_KEY") or "").strip()
        or "dev"
    )


def ip_fingerprint(ip: str) -> str:
    raw = f"{_hash_key()}|{(ip or '').strip()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def mask_ip(ip: str) -> str:
    """Укоротить адрес для журнала: 203.0.113.10 → 203.0.113.xxx."""
    text = (ip or "").strip()
    if not text:
        return ""
    if "xxx" in text or text == "hidden":
        return text[:64]
    if ":" in text:
        parts = [p for p in text.split(":") if p]
        head = ":".join(parts[:3]) if parts else "hidden"
        return (head + ":xxxx")[:64]
    parts = text.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return ".".join(parts[:3]) + ".xxx"
    return "hidden"


def looks_masked(ip: str) -> bool:
    text = ip or ""
    return "xxx" in text or text == "hidden" or not text


def agency_id_for(*, user_id: int | None = None, username: str = "") -> int | None:
    """Чьему агентству принадлежит событие. Чужим кабинетам его не показываем."""
    from webapp.services import access as acc

    user = None
    if user_id:
        user = db.session.get(User, int(user_id))
    elif username:
        user = User.query.filter_by(username=username.strip()).first()
    if not user:
        return None
    try:
        return int(acc.agency_owner_id(user))
    except Exception:
        return int(user.id)


def log_event(
    kind: str,
    *,
    username: str = "",
    detail: str = "",
    user_id: int | None = None,
    agency_user_id: int | None = None,
) -> None:
    try:
        uid = user_id
        if uid is None and getattr(current_user, "is_authenticated", False):
            uid = current_user.id
        uname = (username or "").strip()
        if not uname and getattr(current_user, "is_authenticated", False):
            uname = current_user.username or ""
        ip = client_ip()
        agency = agency_user_id
        if agency is None:
            agency = agency_id_for(user_id=uid, username=uname)
        db.session.add(
            SecurityEvent(
                kind=(kind or "")[:64],
                username=uname[:80],
                ip=mask_ip(ip),
                ip_hash=ip_fingerprint(ip) if ip else "",
                detail=scrub_secrets(detail, limit=500),
                user_id=uid,
                agency_user_id=agency,
            )
        )
        db.session.commit()
    except Exception:
        db.session.rollback()


def _count_since(kind: str, *, since: datetime, username: str = "", ip: str = "") -> int:
    q = SecurityEvent.query.filter(
        SecurityEvent.kind == kind,
        SecurityEvent.created_at >= since,
    )
    total = 0
    uname = (username or "").strip()
    if uname:
        total = max(total, q.filter(SecurityEvent.username == uname).count())
    if ip:
        total = max(total, q.filter(SecurityEvent.ip_hash == ip_fingerprint(ip)).count())
    return total


def login_is_blocked(username: str) -> tuple[bool, str]:
    """Слишком много неудачных входов по логину или IP за окно."""
    since = datetime.utcnow() - timedelta(minutes=LOGIN_WINDOW_MIN)
    uname = (username or "").strip()
    ip = client_ip()
    by_user = _count_since("login_fail", since=since, username=uname) if uname else 0
    by_ip = _count_since("login_fail", since=since, ip=ip) if ip else 0
    if by_user >= LOGIN_MAX_FAILS or by_ip >= LOGIN_MAX_FAILS + 3:
        return True, (
            f"Слишком много неудачных попыток входа. "
            f"Подождите {LOGIN_WINDOW_MIN} минут и попробуйте снова."
        )
    return False, ""


def register_is_blocked() -> tuple[bool, str]:
    since = datetime.utcnow() - timedelta(minutes=REGISTER_WINDOW_MIN)
    ip = client_ip()
    if ip and _count_since("register_attempt", since=since, ip=ip) >= REGISTER_MAX:
        return True, "Слишком много регистраций с этого адреса. Попробуйте позже."
    return False, ""


def portal_is_blocked(token: str) -> tuple[bool, str]:
    """Лимит отправки формы согласования: по IP и по ссылке, без записи самой ссылки."""
    since = datetime.utcnow() - timedelta(minutes=PORTAL_WINDOW_MIN)
    ip = client_ip()
    marker = portal_marker(token)
    by_ip = _count_since("client_portal_post", since=since, ip=ip) if ip else 0
    by_link = _count_since("client_portal_post", since=since, username=marker) if marker else 0
    if by_ip >= PORTAL_MAX or by_link >= PORTAL_MAX:
        return True, "Слишком много действий по этой ссылке. Подождите несколько минут."
    return False, ""


def portal_marker(token: str) -> str:
    if not token:
        return ""
    return "portal:" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def recent_events(agency_user_id: int, limit: int = 50) -> list[SecurityEvent]:
    """События только этого агентства, не соседних кабинетов."""
    return (
        SecurityEvent.query.filter(SecurityEvent.agency_user_id == int(agency_user_id))
        .order_by(SecurityEvent.id.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )


def purge_old_events(retention_days: int | None = None) -> int:
    days = retention_days
    if days is None:
        try:
            from flask import current_app

            days = int(current_app.config.get("SECURITY_LOG_RETENTION_DAYS") or 180)
        except Exception:
            days = 180
    days = max(7, int(days))
    cutoff = datetime.utcnow() - timedelta(days=days)
    deleted = SecurityEvent.query.filter(SecurityEvent.created_at < cutoff).delete(
        synchronize_session=False
    )
    db.session.commit()
    return int(deleted or 0)


def backfill_events() -> None:
    """Старые записи: полный IP заменить на укороченный и привязать к агентству."""
    rows = SecurityEvent.query.filter(
        (SecurityEvent.ip_hash == "")
        | (SecurityEvent.ip_hash.is_(None))
        | (SecurityEvent.agency_user_id.is_(None))
    ).all()
    if not rows:
        return
    changed = False
    for row in rows:
        raw_ip = (row.ip or "").strip()
        if raw_ip and not looks_masked(raw_ip) and not (row.ip_hash or "").strip():
            row.ip_hash = ip_fingerprint(raw_ip)
            row.ip = mask_ip(raw_ip)
            changed = True
        if row.agency_user_id is None:
            row.agency_user_id = agency_id_for(user_id=row.user_id, username=row.username or "")
            changed = True
    if changed:
        db.session.commit()
