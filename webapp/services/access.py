"""Роли агентства: owner / manager / viewer и доступ к каналам."""
from __future__ import annotations

from functools import wraps

from flask import abort, flash, redirect, request, url_for
from flask_login import current_user

from webapp.models import TeamMember, User, Workspace, db


ROLE_OWNER = "owner"
ROLE_MANAGER = "manager"
ROLE_VIEWER = "viewer"

ROLE_LABELS = {
    ROLE_OWNER: "Владелец",
    ROLE_MANAGER: "Менеджер",
    ROLE_VIEWER: "Наблюдатель",
}

# Agency: до 5 сотрудников (+ владелец отдельно)
MAX_TEAM_MEMBERS = 5

# Права по ролям (владелец = всё)
_ROLE_PERMS: dict[str, set[str]] = {
    ROLE_OWNER: {
        "team",
        "billing",
        "workspace_settings",
        "workspace_create",
        "workspace_delete",
        "content",
        "generate",
        "publish",
        "stats",
        "ads",
        "report",
        "view",
    },
    ROLE_MANAGER: {
        "workspace_settings",
        "content",
        "generate",
        "publish",
        "stats",
        "ads",
        "report",
        "view",
    },
    ROLE_VIEWER: {
        "stats",
        "ads",
        "report",
        "view",
    },
}


def plan_allows_team(user: User | None) -> bool:
    """Команда доступна на Agency; на триале/free — тоже для теста."""
    if not user:
        return False
    code = (getattr(user, "plan_code", None) or "free").strip().lower()
    status = (getattr(user, "plan_status", None) or "").strip().lower()
    if code == "agency":
        return True
    if code in {"free"} or status in {"trial", "test_paid"}:
        return True
    return False


def membership_for(user: User) -> TeamMember | None:
    """Если пользователь — сотрудник чужого агентства."""
    if not user or not getattr(user, "id", None):
        return None
    return TeamMember.query.filter_by(user_id=user.id, is_active=True).first()


def agency_owner_id(user: User) -> int:
    """Чьи каналы видит пользователь: свои или владельца агентства."""
    m = membership_for(user)
    if m:
        return int(m.agency_user_id)
    return int(user.id)


def role_for_user(user: User, workspace: Workspace | None = None) -> str:
    """
    Роль относительно кабинета / канала.
    Владелец каналов = owner; сотрудник = manager|viewer.
    """
    if not user:
        return ROLE_VIEWER
    if workspace is not None:
        if workspace.user_id == user.id:
            return ROLE_OWNER
        m = TeamMember.query.filter_by(
            agency_user_id=workspace.user_id,
            user_id=user.id,
            is_active=True,
        ).first()
        if m:
            return (m.role or ROLE_VIEWER).strip().lower()
        return ROLE_VIEWER

    m = membership_for(user)
    if m:
        return (m.role or ROLE_VIEWER).strip().lower()
    return ROLE_OWNER


def can(user: User, perm: str, workspace: Workspace | None = None) -> bool:
    role = role_for_user(user, workspace)
    return perm in _ROLE_PERMS.get(role, set())


def can_access_workspace(user: User, workspace: Workspace | None) -> bool:
    if not user or not workspace:
        return False
    if workspace.user_id == user.id:
        return True
    m = TeamMember.query.filter_by(
        agency_user_id=workspace.user_id,
        user_id=user.id,
        is_active=True,
    ).first()
    return bool(m)


def accessible_workspace_ids(user: User) -> list[int]:
    owner_id = agency_owner_id(user)
    rows = (
        Workspace.query.filter_by(user_id=owner_id, is_active=True)
        .with_entities(Workspace.id)
        .all()
    )
    ids = [int(r[0]) for r in rows]
    # Свои каналы тоже (если сотрудник завёл личные)
    if owner_id != user.id:
        own = (
            Workspace.query.filter_by(user_id=user.id, is_active=True)
            .with_entities(Workspace.id)
            .all()
        )
        for r in own:
            if int(r[0]) not in ids:
                ids.append(int(r[0]))
    return ids


def list_workspaces(user: User, *, active_only: bool = True):
    """Каналы, доступные пользователю (свои + агентства)."""
    ids = accessible_workspace_ids(user)
    if not ids:
        q = Workspace.query.filter_by(user_id=user.id)
        if active_only:
            q = q.filter_by(is_active=True)
        return q.order_by(Workspace.id.asc())
    q = Workspace.query.filter(Workspace.id.in_(ids))
    if active_only:
        q = q.filter_by(is_active=True)
    return q.order_by(Workspace.id.asc())


def get_workspace_or_404(user: User, workspace_id: int) -> Workspace:
    ws = db.session.get(Workspace, workspace_id)
    if not ws or not can_access_workspace(user, ws):
        abort(404)
    return ws


def team_members(agency_user_id: int) -> list[TeamMember]:
    return (
        TeamMember.query.filter_by(agency_user_id=agency_user_id, is_active=True)
        .order_by(TeamMember.id.asc())
        .all()
    )


def team_count(agency_user_id: int) -> int:
    return TeamMember.query.filter_by(agency_user_id=agency_user_id, is_active=True).count()


def require_perm(perm: str, *, workspace_arg: str | None = "workspace_id"):
    """Декоратор: нужен login + право. workspace берётся из kwargs или активного."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login"))
            ws = None
            if workspace_arg and workspace_arg in kwargs and kwargs[workspace_arg] is not None:
                try:
                    ws = get_workspace_or_404(current_user, int(kwargs[workspace_arg]))
                except Exception:
                    ws = None
            if not can(current_user, perm, ws):
                flash("Недостаточно прав для этого действия.", "warning")
                if request.accept_mimetypes.best == "application/json" or (
                    request.path.startswith("/workspaces/") and "json" in (request.path or "")
                ):
                    abort(403)
                return redirect(url_for("smm.manager_panel"))
            return view(*args, **kwargs)

        return wrapped

    return decorator
