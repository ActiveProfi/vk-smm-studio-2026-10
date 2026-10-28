"""Выгрузка и удаление данных аккаунта (права субъекта по 152-ФЗ).

Токены ВК и VK Реклама в выгрузку не попадают — только отметка, что они заданы.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from flask import current_app

from webapp.models import (
    ApiUsageLog,
    ContentPlanBatch,
    Draft,
    Rubric,
    SecurityEvent,
    TeamMember,
    User,
    Workspace,
    db,
)
def _stamp(value) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


def export_account(user: User) -> dict:
    workspaces = Workspace.query.filter_by(user_id=user.id).order_by(Workspace.id.asc()).all()
    ws_ids = [w.id for w in workspaces]
    drafts = []
    if ws_ids:
        drafts = (
            Draft.query.filter(Draft.workspace_id.in_(ws_ids))
            .order_by(Draft.id.asc())
            .all()
        )
    own_drafts = Draft.query.filter_by(user_id=user.id).order_by(Draft.id.asc()).all()
    seen = {d.id for d in drafts}
    for draft in own_drafts:
        if draft.id not in seen:
            drafts.append(draft)

    plans = []
    if ws_ids:
        plans = ContentPlanBatch.query.filter(ContentPlanBatch.workspace_id.in_(ws_ids)).all()

    events = (
        SecurityEvent.query.filter(SecurityEvent.agency_user_id == user.id)
        .order_by(SecurityEvent.id.desc())
        .limit(200)
        .all()
    )
    members = TeamMember.query.filter_by(agency_user_id=user.id, is_active=True).all()

    return {
        "exported_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "note": "Токены ВК и секреты рекламы в файл не включены.",
        "account": {
            "id": user.id,
            "username": user.username,
            "created_at": _stamp(user.created_at),
            "plan_code": user.plan_code or "",
            "plan_status": user.plan_status or "",
            "privacy_accepted_at": user.privacy_accepted_at or "",
            "privacy_policy_version": user.privacy_policy_version or "",
        },
        "workspaces": [
            {
                "id": w.id,
                "name": w.name,
                "theme": w.theme or "",
                "description": w.description or "",
                "vk_group_id": w.vk_group_id or "",
                "vk_token_saved": bool((w.vk_token or "").strip()),
                "vk_ads_connected": bool((w.vk_ads_token or "").strip() or (w.vk_ads_client_id or "").strip()),
                "package_code": w.package_code or "",
                "created_at": _stamp(w.created_at),
            }
            for w in workspaces
        ],
        "drafts": [
            {
                "id": d.id,
                "workspace_id": d.workspace_id,
                "topic": d.topic or "",
                "status": d.status or "",
                "scheduled_for": d.scheduled_for or "",
                "post_text": d.post_text or "",
                "created_at": _stamp(d.created_at),
            }
            for d in drafts
        ],
        "content_plans": [
            {
                "id": p.id,
                "workspace_id": p.workspace_id,
                "title": p.title or "",
                "client_status": p.client_status or "",
                "client_comment": p.client_comment or "",
                "items_json": p.items_json or "[]",
            }
            for p in plans
        ],
        "team": [
            {
                "member_user_id": m.user_id,
                "role": m.role or "",
                "username": (db.session.get(User, m.user_id).username if db.session.get(User, m.user_id) else ""),
            }
            for m in members
        ],
        "security_log": [
            {
                "at": _stamp(e.created_at),
                "kind": e.kind or "",
                "username": e.username or "",
                "ip_masked": e.ip or "",
                "detail": e.detail or "",
            }
            for e in events
        ],
    }


def delete_account(user: User) -> None:
    """Удалить кабинет, каналы, черновики, журнал и загруженные файлы этого пользователя."""
    user_id = int(user.id)
    owned = Workspace.query.filter_by(user_id=user_id).all()
    ws_ids = [w.id for w in owned]

    if ws_ids:
        Draft.query.filter(Draft.workspace_id.in_(ws_ids)).delete(synchronize_session=False)
        ContentPlanBatch.query.filter(ContentPlanBatch.workspace_id.in_(ws_ids)).delete(
            synchronize_session=False
        )
        Rubric.query.filter(Rubric.workspace_id.in_(ws_ids)).delete(synchronize_session=False)
        ApiUsageLog.query.filter(ApiUsageLog.workspace_id.in_(ws_ids)).delete(synchronize_session=False)
        User.query.filter(User.active_workspace_id.in_(ws_ids)).update(
            {User.active_workspace_id: None},
            synchronize_session=False,
        )
        Workspace.query.filter(Workspace.id.in_(ws_ids)).delete(synchronize_session=False)

    # Черновики в канале чужого агентства остаются агентству: убираем только ссылку на удалённого сотрудника.
    foreign_drafts = Draft.query.filter(
        Draft.user_id == user_id,
        Draft.workspace_id.isnot(None),
    ).all()
    for draft in foreign_drafts:
        channel = db.session.get(Workspace, draft.workspace_id)
        if channel and channel.user_id != user_id:
            draft.user_id = channel.user_id
    Draft.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    ApiUsageLog.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    ContentPlanBatch.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    TeamMember.query.filter(
        (TeamMember.user_id == user_id) | (TeamMember.agency_user_id == user_id)
    ).delete(synchronize_session=False)
    SecurityEvent.query.filter(
        (SecurityEvent.user_id == user_id) | (SecurityEvent.agency_user_id == user_id)
    ).delete(synchronize_session=False)

    User.query.filter(User.active_workspace_id.isnot(None)).filter(
        User.id == user_id
    ).update({User.active_workspace_id: None}, synchronize_session=False)

    db.session.delete(user)
    db.session.commit()

    upload_root = Path(current_app.config["UPLOAD_FOLDER"]) / str(user_id)
    if upload_root.exists():
        shutil.rmtree(upload_root, ignore_errors=True)
