"""Вернуть просроченный пост в активный контент-план канала.

Записи не удаляются: меняются дата, статус и привязка к плану.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from webapp.models import ContentPlanBatch, Draft, Workspace, db
from webapp.services import schedule_queue as sq
from webapp.services.publish_formats import label as format_label
from webapp.services.publish_formats import normalize_format


def active_content_plan(ws: Workspace) -> ContentPlanBatch | None:
    """Свежий согласованный план, иначе свежий план на согласовании."""
    plans = (
        ContentPlanBatch.query.filter_by(workspace_id=ws.id)
        .order_by(ContentPlanBatch.id.desc())
        .all()
    )
    for status in ("approved", "pending"):
        for plan in plans:
            if (plan.client_status or "") == status:
                return plan
    return None


def _used_days(ws: Workspace) -> set[date]:
    used: set[date] = set()
    for draft in Draft.query.filter_by(workspace_id=ws.id).all():
        moment = sq.parse_scheduled_dt(draft.scheduled_for)
        if moment:
            used.add(moment.date())
    return used


def next_free_slot(ws: Workspace, *, start: date | None = None) -> str:
    """Ближайший свободный день, 10:00, пояс +10 как в остальных датах кабинета."""
    used = _used_days(ws)
    day = start or (date.today() + timedelta(days=1))
    if start is None and day <= date.today():
        day = date.today() + timedelta(days=1)
    for _ in range(90):
        if day not in used:
            return f"{day.isoformat()}T10:00:00+10:00"
        day += timedelta(days=1)
    return f"{day.isoformat()}T10:00:00+10:00"


def slot_from_choice(raw: str | None) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        day = date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ValueError("Дата должна быть в виде ГГГГ-ММ-ДД.") from exc
    if day < date.today():
        raise ValueError("Выберите сегодняшнюю или будущую дату.")
    return f"{day.isoformat()}T10:00:00+10:00"


def is_overdue(draft: Draft, *, now: datetime | None = None) -> bool:
    """Дата публикации уже прошла, а пост ещё не опубликован."""
    if (draft.status or "") == sq.STATUS_PUBLISHED:
        return False
    moment = sq.parse_scheduled_dt(draft.scheduled_for)
    if not moment:
        return False
    current = now or sq.now_tz(moment.tzinfo)
    if current.tzinfo is None and moment.tzinfo is not None:
        current = current.replace(tzinfo=moment.tzinfo)
    return current > moment


def return_draft_to_active_plan(draft: Draft, *, chosen_date: str = "") -> str:
    """Поставить пост в активный план. Возвращает подпись новой даты."""
    from webapp.services.business import plan_items_from_json
    import json

    ws = draft.workspace
    if not ws:
        raise ValueError("У поста нет канала.")
    plan = active_content_plan(ws)
    if not plan:
        raise ValueError(
            f"У канала «{ws.name}» нет активного контент-плана. "
            "Откройте «Контент-план», соберите план и повторите."
        )
    slot = slot_from_choice(chosen_date) if (chosen_date or "").strip() else next_free_slot(ws)
    kept_text = draft.post_text or ""
    draft.scheduled_for = slot
    draft.content_plan_id = plan.id
    draft.post_text = kept_text
    if kept_text.strip():
        draft.status = sq.STATUS_READY
    else:
        draft.status = sq.STATUS_PLANNED

    items = plan_items_from_json(plan.items_json)
    fmt = normalize_format(getattr(draft, "publish_format", "") or "image")
    items.append(
        {
            "topic": (draft.topic or "Без темы")[:300],
            "rubric_code": (draft.post_type or "")[:64],
            "rubric_title": "",
            "scheduled_for": slot,
            "note": "Вернули из просроченных",
            "format": fmt,
            "format_label": format_label(fmt),
        }
    )
    plan.items_json = json.dumps(items, ensure_ascii=False)
    db.session.commit()
    return sq.format_publish_at(slot)
