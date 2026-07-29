"""Вариант B: генерация материалов за N часов до публикации.

Правило:
- после утверждения плана пост = planned (тема + дата, без текста/визуала);
- когда до scheduled_for осталось <= GENERATE_AHEAD_HOURS — пора генерировать;
- готовый комплект → ready; публикатор берёт только ready в срок.

Панель менеджера по всем каналам — отдельный этап (см. list_generation_due).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from webapp.models import Draft

# За сколько часов до публикации нужно готовить материалы
GENERATE_AHEAD_HOURS = 24

STATUS_PLANNED = "planned"
STATUS_DRAFT = "draft"
STATUS_GENERATING = "generating"
STATUS_READY = "ready"
STATUS_PUBLISHED = "published"
STATUS_ERROR = "error"

STATUS_LABELS_RU = {
    STATUS_PLANNED: "в плане",
    STATUS_DRAFT: "черновик",
    STATUS_GENERATING: "генерация",
    STATUS_READY: "готов к публикации",
    STATUS_PUBLISHED: "опубликован",
    STATUS_ERROR: "ошибка",
}


def parse_scheduled_dt(value: str | None) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        normalized = raw.replace("Z", "+00:00")
        if " " in normalized and "T" not in normalized:
            normalized = normalized.replace(" ", "T", 1)
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            # Как в формах календаря: по умолчанию +10
            dt = dt.replace(tzinfo=timezone(timedelta(hours=10)))
        return dt
    except ValueError:
        return None


def now_tz(tz: timezone | None = None) -> datetime:
    return datetime.now(tz or timezone(timedelta(hours=10)))


def has_publish_materials(draft: Draft) -> bool:
    """Есть ли текст и хотя бы один визуал для публикации."""
    text_ok = bool((draft.post_text or "").strip())
    visual_ok = bool((draft.image_url or "").strip() or (draft.video_url or "").strip())
    return text_ok and visual_ok


def generation_window_start(scheduled: datetime) -> datetime:
    return scheduled - timedelta(hours=GENERATE_AHEAD_HOURS)


def needs_generation(draft: Draft, *, now: datetime | None = None) -> bool:
    """True, если пора готовить материалы (окно за сутки до даты и позже, пока не ready)."""
    if (draft.status or "") in {STATUS_READY, STATUS_PUBLISHED, STATUS_GENERATING}:
        return False
    if has_publish_materials(draft):
        return False
    scheduled = parse_scheduled_dt(draft.scheduled_for)
    if not scheduled:
        return False
    current = now or now_tz(scheduled.tzinfo)
    if current.tzinfo is None and scheduled.tzinfo is not None:
        current = current.replace(tzinfo=scheduled.tzinfo)
    return current >= generation_window_start(scheduled)


def hours_until_publish(draft: Draft, *, now: datetime | None = None) -> float | None:
    scheduled = parse_scheduled_dt(draft.scheduled_for)
    if not scheduled:
        return None
    current = now or now_tz(scheduled.tzinfo)
    if current.tzinfo is None and scheduled.tzinfo is not None:
        current = current.replace(tzinfo=scheduled.tzinfo)
    return (scheduled - current).total_seconds() / 3600.0


def urgency_label(draft: Draft, *, now: datetime | None = None) -> str:
    if not needs_generation(draft, now=now):
        return ""
    hours = hours_until_publish(draft, now=now)
    if hours is None:
        return "нужна генерация"
    if hours < 0:
        return "просрочено — срочно сгенерировать"
    if hours <= 6:
        return "срочно: осталось меньше 6 ч"
    if hours <= GENERATE_AHEAD_HOURS:
        return f"за сутки: осталось ~{int(hours)} ч"
    return "нужна генерация"


def filter_due_for_generation(
    drafts: Iterable[Draft],
    *,
    now: datetime | None = None,
) -> list[Draft]:
    due = [d for d in drafts if needs_generation(d, now=now)]
    due.sort(key=lambda d: parse_scheduled_dt(d.scheduled_for) or datetime.max.replace(tzinfo=timezone.utc))
    return due


def status_label_ru(status: str | None) -> str:
    key = (status or "").strip()
    return STATUS_LABELS_RU.get(key, key or "—")


_WEEKDAYS_RU = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
_MONTHS_RU = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def format_publish_at(value: str | None) -> str:
    """Понятная дата публикации: «пн, 28 июля 2026 · 10:00»."""
    dt = parse_scheduled_dt(value)
    if not dt:
        raw = (value or "").strip()
        return raw or "—"
    weekday = _WEEKDAYS_RU[dt.weekday()]
    month = _MONTHS_RU[dt.month]
    return f"{weekday}, {dt.day} {month} {dt.year} · {dt.hour:02d}:{dt.minute:02d}"


def summarize_channel(
    workspace,
    drafts: list[Draft],
    *,
    rubric_count: int = 0,
    now: datetime | None = None,
) -> dict:
    """Сводка по одному каналу для панели управления менеджера."""
    current = now or now_tz()
    due_list = filter_due_for_generation(drafts, now=current)
    planned = 0
    ready = 0
    published = 0
    draft_n = 0
    error_n = 0
    generating = 0
    next_dt = None
    next_topic = ""
    next_scheduled = ""
    overdue = 0

    for d in drafts:
        st = (d.status or "").strip()
        if st == STATUS_PLANNED:
            planned += 1
        elif st == STATUS_READY:
            ready += 1
        elif st == STATUS_PUBLISHED:
            published += 1
        elif st == STATUS_GENERATING:
            generating += 1
        elif st == STATUS_ERROR:
            error_n += 1
        else:
            draft_n += 1

        if needs_generation(d, now=current):
            hours = hours_until_publish(d, now=current)
            if hours is not None and hours < 0:
                overdue += 1

        dt = parse_scheduled_dt(d.scheduled_for)
        if dt and st != STATUS_PUBLISHED:
            if next_dt is None or dt < next_dt:
                next_dt = dt
                next_topic = (d.topic or "").strip()
                next_scheduled = d.scheduled_for or ""

    alert = ""
    if overdue:
        alert = f"Срочно: {overdue} пост(ов) с просроченной подготовкой"
    elif due_list:
        alert = f"Нужно сгенерировать материалы: {len(due_list)} (за {GENERATE_AHEAD_HOURS} ч до публикации)"

    return {
        "workspace": workspace,
        "rubric_count": rubric_count,
        "total": len(drafts),
        "planned": planned,
        "due": len(due_list),
        "due_items": due_list[:5],
        "overdue": overdue,
        "ready": ready,
        "published": published,
        "draft": draft_n,
        "generating": generating,
        "error": error_n,
        "alert": alert,
        "next_publish_at": format_publish_at(next_scheduled),
        "next_topic": next_topic[:120],
        "has_vk": bool((getattr(workspace, "vk_group_id", None) or "").strip()),
    }


def build_manager_board(
    workspaces: list,
    drafts: list[Draft],
    *,
    rubric_counts: dict[int, int] | None = None,
    now: datetime | None = None,
) -> dict:
    """Панель менеджера: карточки каналов + общие уведомления."""
    current = now or now_tz()
    by_ws: dict[int, list[Draft]] = {}
    for d in drafts:
        if not d.workspace_id:
            continue
        by_ws.setdefault(int(d.workspace_id), []).append(d)

    counts = rubric_counts or {}
    rows = []
    for ws in workspaces:
        rows.append(
            summarize_channel(
                ws,
                by_ws.get(int(ws.id), []),
                rubric_count=int(counts.get(int(ws.id), 0)),
                now=current,
            )
        )

    # Каналы с задачей наверху
    rows.sort(key=lambda r: (-r["overdue"], -r["due"], r["workspace"].name.lower()))

    notifications = []
    for r in rows:
        if r["alert"]:
            notifications.append(
                {
                    "workspace_id": r["workspace"].id,
                    "workspace_name": r["workspace"].name,
                    "text": r["alert"],
                    "due": r["due"],
                    "overdue": r["overdue"],
                }
            )

    totals = {
        "channels": len(rows),
        "due": sum(r["due"] for r in rows),
        "overdue": sum(r["overdue"] for r in rows),
        "planned": sum(r["planned"] for r in rows),
        "ready": sum(r["ready"] for r in rows),
        "published": sum(r["published"] for r in rows),
    }
    return {
        "rows": rows,
        "notifications": notifications,
        "totals": totals,
        "ahead_hours": GENERATE_AHEAD_HOURS,
    }
