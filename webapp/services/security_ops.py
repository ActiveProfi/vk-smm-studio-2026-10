"""Безопасность: лимит входа, журнал действий, баннер DEV_SKIP."""
from __future__ import annotations

from datetime import datetime, timedelta

from flask import request
from flask_login import current_user

from webapp.models import SecurityEvent, db


LOGIN_WINDOW_MIN = 15
LOGIN_MAX_FAILS = 7


def client_ip() -> str:
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return forwarded or (request.remote_addr or "")


def log_event(
    kind: str,
    *,
    username: str = "",
    detail: str = "",
    user_id: int | None = None,
) -> None:
    try:
        uid = user_id
        if uid is None and getattr(current_user, "is_authenticated", False):
            uid = current_user.id
        uname = (username or "").strip()
        if not uname and getattr(current_user, "is_authenticated", False):
            uname = current_user.username or ""
        db.session.add(
            SecurityEvent(
                kind=(kind or "")[:64],
                username=uname[:80],
                ip=client_ip()[:64],
                detail=(detail or "")[:500],
                user_id=uid,
            )
        )
        db.session.commit()
    except Exception:
        db.session.rollback()


def login_is_blocked(username: str) -> tuple[bool, str]:
    """Слишком много неудачных входов по логину или IP за окно."""
    since = datetime.utcnow() - timedelta(minutes=LOGIN_WINDOW_MIN)
    uname = (username or "").strip()
    ip = client_ip()

    q = SecurityEvent.query.filter(
        SecurityEvent.kind == "login_fail",
        SecurityEvent.created_at >= since,
    )
    by_user = q.filter(SecurityEvent.username == uname).count() if uname else 0
    by_ip = q.filter(SecurityEvent.ip == ip).count() if ip else 0

    if by_user >= LOGIN_MAX_FAILS or by_ip >= LOGIN_MAX_FAILS + 3:
        return True, (
            f"Слишком много неудачных попыток входа. "
            f"Подождите {LOGIN_WINDOW_MIN} минут и попробуйте снова."
        )
    return False, ""


def recent_events(limit: int = 50) -> list[SecurityEvent]:
    return (
        SecurityEvent.query.order_by(SecurityEvent.id.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
