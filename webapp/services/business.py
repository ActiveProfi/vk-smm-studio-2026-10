"""Бизнес-слой: пакеты, согласование, расходы API, отчёт, автопубликация."""
from __future__ import annotations

import secrets
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from typing import Any

from webapp.models import ApiUsageLog, ContentPlanBatch, Draft, Rubric, Workspace, db
from webapp.services import schedule_queue as sq

PACKAGE_PRESETS = {
    "none": {"title": "Без пакета", "limit": 0},
    "start": {"title": "Старт · 12 постов/мес", "limit": 12},
    "business": {"title": "Бизнес · 25 постов/мес", "limit": 25},
    "premium": {"title": "Премиум · 45 постов/мес + видео", "limit": 45},
    "custom": {"title": "Свой лимит", "limit": 25},
}

# Оценка затрат (руб.) — можно переопределить в .env: API_COST_TEXT_RUB и т.д.
def _env_cost(key: str, default: float) -> float:
    import os

    raw = (os.environ.get(key) or "").strip().replace(",", ".")
    if not raw:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        return default


def resolve_unit_cost(kind: str) -> float:
    """Актуальный тариф (читает .env при каждом вызове)."""
    defaults = {
        "text": ("API_COST_TEXT_RUB", 3.0),
        "image": ("API_COST_IMAGE_RUB", 8.0),
        "video": ("API_COST_VIDEO_RUB", 25.0),
        "plan": ("API_COST_PLAN_RUB", 5.0),
        "marketer": ("API_COST_MARKETER_RUB", 5.0),
    }
    code = (kind or "text").strip()
    env_key, fallback = defaults.get(code, ("", 3.0))
    return _env_cost(env_key, fallback) if env_key else fallback


# Кэш для подсказок в UI (обновляется при старте процесса)
DEFAULT_COSTS_RUB = {
    "text": resolve_unit_cost("text"),
    "image": resolve_unit_cost("image"),
    "video": resolve_unit_cost("video"),
    "plan": resolve_unit_cost("plan"),
    "marketer": resolve_unit_cost("marketer"),
}

KIND_LABELS_RU = {
    "text": "Текст поста",
    "image": "Картинка",
    "video": "Видео",
    "plan": "Контент-план (ИИ)",
    "marketer": "Резюме маркетолога",
}


def usage_kind_title(kind: str | None) -> str:
    code = (kind or "").strip()
    return KIND_LABELS_RU.get(code, code or "Прочее")


def cost_tariffs_for_ui() -> list[dict[str, Any]]:
    """Тарифы для подсказки в отчёте (оценка для агентства)."""
    order = ("text", "image", "video", "plan", "marketer")
    return [
        {
            "kind": k,
            "title": usage_kind_title(k),
            "unit_rub": float(resolve_unit_cost(k)),
        }
        for k in order
    ]


def ensure_client_token(ws: Workspace) -> str:
    token = (ws.client_approve_token or "").strip()
    if token:
        return token
    token = secrets.token_urlsafe(24)
    ws.client_approve_token = token
    db.session.commit()
    return token


def package_title(code: str | None) -> str:
    return PACKAGE_PRESETS.get((code or "business"), PACKAGE_PRESETS["business"])["title"]


def resolve_package_limit(ws: Workspace) -> int:
    code = (ws.package_code or "business").strip()
    if code == "custom":
        return int(ws.package_posts_limit or 0)
    if code == "none":
        return 0
    return int(PACKAGE_PRESETS.get(code, PACKAGE_PRESETS["business"])["limit"])


def period_bounds(ws: Workspace, *, today: date | None = None) -> tuple[date, date]:
    """Текущий расчётный месяц пакета."""
    today = today or date.today()
    raw = (ws.package_period_start or "").strip()
    start: date
    try:
        if raw:
            start = date.fromisoformat(raw[:10]).replace(day=1)
        else:
            start = today.replace(day=1)
    except ValueError:
        start = today.replace(day=1)
    # если период в прошлом месяце относительно today — сдвигаем на текущий месяц
    if start.year != today.year or start.month != today.month:
        start = today.replace(day=1)
    last = monthrange(start.year, start.month)[1]
    end = date(start.year, start.month, last)
    return start, end


def _draft_in_period(d: Draft, start: date, end: date) -> bool:
    dt = sq.parse_scheduled_dt(d.scheduled_for)
    if dt:
        day = dt.date()
        return start <= day <= end
    if d.created_at:
        day = d.created_at.date()
        return start <= day <= end
    return False


def count_package_posts_used(ws: Workspace) -> int:
    """Слоты пакета за месяц: посты в календаре / готовые / опубликованные / в генерации."""
    start, end = period_bounds(ws)
    drafts = Draft.query.filter_by(workspace_id=ws.id).all()
    used = 0
    counted_statuses = {
        sq.STATUS_PLANNED,
        sq.STATUS_GENERATING,
        sq.STATUS_READY,
        sq.STATUS_PUBLISHED,
    }
    for d in drafts:
        if not _draft_in_period(d, start, end):
            continue
        st = (d.status or "").strip()
        if st in counted_statuses:
            used += 1
        elif st == sq.STATUS_DRAFT and sq.has_publish_materials(d):
            # черновик с материалами тоже занимает слот
            used += 1
    return used


def package_status(ws: Workspace) -> dict[str, Any]:
    limit = resolve_package_limit(ws)
    used = count_package_posts_used(ws)
    start, end = period_bounds(ws)
    unlimited = limit <= 0
    left = None if unlimited else max(0, limit - used)
    blocked = (not unlimited) and used >= limit
    percent = 0
    if not unlimited and limit > 0:
        percent = min(100, int(round(100 * used / limit)))
    return {
        "code": (ws.package_code or "business"),
        "title": package_title(ws.package_code),
        "limit": limit,
        "used": used,
        "left": left,
        "unlimited": unlimited,
        "blocked": blocked,
        "percent": percent,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "period_label": f"{start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}",
    }


def assert_can_generate_post(ws: Workspace) -> None:
    st = package_status(ws)
    if st["blocked"]:
        raise ValueError(
            f"Лимит пакета «{st['title']}» исчерпан: {st['used']}/{st['limit']} "
            f"за период {st['period_label']}. Смените пакет в настройках канала "
            f"или дождитесь нового месяца."
        )


def assert_can_add_posts(ws: Workspace, add_count: int) -> None:
    """Проверка перед внесением нескольких тем из контент-плана."""
    add_count = max(0, int(add_count or 0))
    if add_count <= 0:
        return
    st = package_status(ws)
    if st["unlimited"]:
        return
    limit = int(st["limit"] or 0)
    used = int(st["used"] or 0)
    if used + add_count > limit:
        left = max(0, limit - used)
        raise ValueError(
            f"Пакет «{st['title']}»: осталось {left} из {limit} постов в этом месяце, "
            f"а в плане тем: {add_count}. Уменьшите план или смените пакет."
        )


def log_api_usage(
    *,
    user_id: int,
    workspace_id: int | None,
    kind: str,
    units: int = 1,
    note: str = "",
    cost_rub: float | None = None,
) -> None:
    kind = (kind or "text").strip()
    unit_cost = resolve_unit_cost(kind)
    cost = float(cost_rub) if cost_rub is not None else unit_cost * max(1, units)
    db.session.add(
        ApiUsageLog(
            user_id=user_id,
            workspace_id=workspace_id,
            kind=kind,
            units=max(1, units),
            cost_rub=cost,
            note=(note or "")[:300],
        )
    )
    db.session.commit()


def usage_costs_for_period(
    workspace_id: int,
    *,
    start: date,
    end: date,
) -> dict[str, Any]:
    start_dt = datetime(start.year, start.month, start.day)
    end_dt = datetime(end.year, end.month, end.day, 23, 59, 59)
    rows = (
        ApiUsageLog.query.filter_by(workspace_id=workspace_id)
        .filter(ApiUsageLog.created_at >= start_dt)
        .filter(ApiUsageLog.created_at <= end_dt)
        .order_by(ApiUsageLog.id.desc())
        .all()
    )
    by_kind: dict[str, dict[str, float]] = {}
    total = 0.0
    events: list[dict[str, Any]] = []
    for r in rows:
        bucket = by_kind.setdefault(r.kind, {"count": 0, "cost": 0.0})
        bucket["count"] += int(r.units or 1)
        bucket["cost"] += float(r.cost_rub or 0)
        total += float(r.cost_rub or 0)
        events.append(
            {
                "when": r.created_at.strftime("%d.%m.%Y %H:%M") if r.created_at else "—",
                "kind": r.kind,
                "title": usage_kind_title(r.kind),
                "units": int(r.units or 1),
                "cost": round(float(r.cost_rub or 0), 2),
                "note": (r.note or "").strip(),
            }
        )
    return {
        "by_kind": by_kind,
        "total_rub": round(total, 2),
        "events": len(rows),
        "event_rows": events,
    }


def month_api_costs(ws: Workspace, *, year: int | None = None, month: int | None = None) -> dict[str, Any]:
    """Краткая сводка расходов API за месяц — для панели менеджера."""
    now = date.today()
    y = int(year or now.year)
    m = int(month or now.month)
    start = date(y, m, 1)
    end = date(y, m, monthrange(y, m)[1])
    costs = usage_costs_for_period(ws.id, start=start, end=end)
    return {
        "year": y,
        "month": m,
        "period_label": month_title_ru(y, m),
        "total_rub": costs["total_rub"],
        "events": costs["events"],
        "cost_rows": [
            {
                "kind": kind,
                "title": usage_kind_title(kind),
                "count": int(info.get("count") or 0),
                "cost": round(float(info.get("cost") or 0), 2),
            }
            for kind, info in sorted((costs.get("by_kind") or {}).items())
        ],
    }

def build_month_report(ws: Workspace, *, year: int, month: int) -> dict[str, Any]:
    start = date(year, month, 1)
    last = monthrange(year, month)[1]
    end = date(year, month, last)
    drafts = Draft.query.filter_by(workspace_id=ws.id).all()
    in_month = [d for d in drafts if _draft_in_period(d, start, end)]
    rubrics = {
        r.code: r.title
        for r in Rubric.query.filter_by(workspace_id=ws.id).all()
    }
    by_rubric: dict[str, int] = {}
    counts = {
        "planned": 0,
        "ready": 0,
        "published": 0,
        "pending_approval": 0,
        "rejected": 0,
        "total": len(in_month),
    }
    posts = []
    for d in in_month:
        st = (d.status or "").strip()
        if st == sq.STATUS_PLANNED:
            counts["planned"] += 1
        elif st == sq.STATUS_READY:
            counts["ready"] += 1
        elif st == sq.STATUS_PUBLISHED:
            counts["published"] += 1
        if (d.client_status or "") == "pending":
            counts["pending_approval"] += 1
        if (d.client_status or "") == "rejected":
            counts["rejected"] += 1
        code = d.post_type or "—"
        title = rubrics.get(code, code)
        by_rubric[title] = by_rubric.get(title, 0) + 1
        posts.append(
            {
                "id": d.id,
                "topic": d.topic or "—",
                "rubric": title,
                "status": sq.status_label_ru(st),
                "client_status": d.client_status or "none",
                "client_status_label": client_status_label(d.client_status),
                "when": sq.format_publish_at(d.scheduled_for),
                "vk_post_id": d.vk_post_id or "",
            }
        )
    costs = usage_costs_for_period(ws.id, start=start, end=end)
    pkg = package_status(ws)
    # Важно: не называть ключ "items" — в Jinja report.items это метод dict, не список
    return {
        "workspace": ws,
        "year": year,
        "month": month,
        "period_label": f"{start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}",
        "counts": counts,
        "by_rubric": sorted(by_rubric.items(), key=lambda x: -x[1]),
        "posts": posts,
        "costs": costs,
        "cost_rows": [
            {
                "kind": kind,
                "title": usage_kind_title(kind),
                "count": int(info.get("count") or 0),
                "cost": float(info.get("cost") or 0),
                "unit_rub": float(resolve_unit_cost(kind)),
            }
            # Скобки обязательны: иначе при непустом by_kind sorted() идёт по ключам-строкам
            for kind, info in sorted((costs.get("by_kind") or {}).items())
        ],
        "cost_events": costs.get("event_rows") or [],
        "cost_tariffs": cost_tariffs_for_ui(),
        "package": pkg,
    }


def can_auto_publish(draft: Draft, ws: Workspace) -> tuple[bool, str]:
    if (draft.status or "") == sq.STATUS_PUBLISHED:
        return False, "уже опубликован"
    if not sq.has_publish_materials(draft):
        return False, "нет текста/визуала"
    if (draft.status or "") != sq.STATUS_READY:
        return False, "нужен статус ready"
    # Согласование — на уровне контент-плана, не поста
    if bool(ws.require_client_approval) and draft.content_plan_id:
        plan = db.session.get(ContentPlanBatch, draft.content_plan_id)
        if plan and (plan.client_status or "") != "approved":
            return False, "контент-план ещё не согласован клиентом"
    scheduled = sq.parse_scheduled_dt(draft.scheduled_for)
    if not scheduled:
        return False, "нет даты публикации"
    now = sq.now_tz(scheduled.tzinfo)
    if now < scheduled:
        return False, "время ещё не наступило"
    return True, "ok"


def due_auto_publish_drafts(ws: Workspace) -> list[Draft]:
    drafts = (
        Draft.query.filter_by(workspace_id=ws.id)
        .filter(Draft.scheduled_for != "")
        .order_by(Draft.scheduled_for.asc())
        .all()
    )
    out = []
    for d in drafts:
        ok, _ = can_auto_publish(d, ws)
        if ok:
            out.append(d)
    return out


def auto_publish_queue_info(ws: Workspace) -> dict[str, Any]:
    """Сколько постов ждут автопубликации и сколько уже «просрочены» по времени."""
    from webapp.services import auto_publish_worker as apw

    enabled = bool(ws.auto_publish_enabled)
    drafts = (
        Draft.query.filter_by(workspace_id=ws.id, status=sq.STATUS_READY)
        .filter(Draft.scheduled_for != "")
        .order_by(Draft.scheduled_for.asc())
        .all()
    )
    waiting = 0  # ready, время ещё не наступило
    due_now = 0  # можно публиковать прямо сейчас
    blocked = 0  # ready, но план не согласован и т.п.
    next_at = ""
    for d in drafts:
        ok, reason = can_auto_publish(d, ws)
        if ok:
            due_now += 1
            continue
        if reason == "время ещё не наступило":
            waiting += 1
            if not next_at:
                next_at = (d.scheduled_for or "").strip()
        elif reason not in {"уже опубликован", "нет даты публикации"}:
            blocked += 1
    last = apw.last_run(ws.id) or {}
    return {
        "enabled": enabled,
        "due_now": due_now,
        "waiting": waiting,
        "blocked": blocked,
        "next_at": next_at,
        "last_at": last.get("at") or "",
        "last_published": int(last.get("published") or 0),
        "last_checked": int(last.get("checked") or 0),
        "last_ok": bool(last.get("ok")) if last else None,
        "last_error": (last.get("error") or ""),
    }


def plan_items_from_json(raw: str | None) -> list[dict]:
    import json

    try:
        data = json.loads(raw or "[]")
    except Exception:  # noqa: BLE001
        return []
    return data if isinstance(data, list) else []


def create_plan_for_client(
    *,
    ws: Workspace,
    user_id: int,
    items: list[dict],
    start_date: str = "",
    days: int = 7,
    audience_summary: str = "",
    timing_logic: str = "",
) -> ContentPlanBatch:
    """Сохранить контент-план и отправить клиенту на согласование целиком."""
    import json

    clean: list[dict] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        topic = str(raw.get("topic") or "").strip()
        if len(topic) < 3:
            continue
        clean.append(
            {
                "topic": topic[:300],
                "rubric_code": str(raw.get("rubric_code") or "").strip(),
                "rubric_title": str(raw.get("rubric_title") or "").strip(),
                "scheduled_for": str(raw.get("scheduled_for") or "").strip(),
                "note": str(raw.get("note") or "").strip(),
                "format": str(raw.get("format") or "").strip(),
            }
        )
    if not clean:
        raise ValueError("В плане нет тем для согласования.")

    title = f"План на {days} дн."
    if start_date:
        title = f"План с {start_date} · {days} дн. · {len(clean)} тем"
    else:
        title = f"План · {days} дн. · {len(clean)} тем"

    ensure_client_token(ws)
    batch = ContentPlanBatch(
        workspace_id=ws.id,
        user_id=user_id,
        title=title,
        start_date=(start_date or "")[:32],
        days=int(days or 7),
        items_json=json.dumps(clean, ensure_ascii=False),
        audience_summary=(audience_summary or "")[:5000],
        timing_logic=(timing_logic or "")[:3000],
        client_status="pending",
        client_comment="",
        saved_to_calendar=False,
    )
    db.session.add(batch)
    db.session.commit()
    return batch


def list_content_plans(ws: Workspace) -> list[ContentPlanBatch]:
    return (
        ContentPlanBatch.query.filter_by(workspace_id=ws.id)
        .order_by(ContentPlanBatch.id.desc())
        .all()
    )


def count_pending_plan_approvals(ws: Workspace) -> int:
    return ContentPlanBatch.query.filter_by(
        workspace_id=ws.id, client_status="pending"
    ).count()


def decide_content_plan(
    plan: ContentPlanBatch, *, decision: str, comment: str = ""
) -> None:
    decision = (decision or "").strip()
    if (plan.client_status or "") != "pending":
        raise ValueError("Этот план уже не ждёт согласования.")
    if decision == "approve":
        plan.client_status = "approved"
        plan.client_comment = (comment or "").strip()[:1000]
    elif decision == "reject":
        plan.client_status = "rejected"
        plan.client_comment = ((comment or "").strip() or "Нужны правки")[:1000]
    else:
        raise ValueError("Выберите «Согласовать» или «На правки».")
    db.session.commit()


def create_planned_drafts_from_items(
    *,
    ws: Workspace,
    user_id: int,
    items: list,
    content_plan_id: int | None = None,
) -> list[int]:
    """Создать черновики status=planned из строк контент-плана."""
    rubrics = {
        r.code: r
        for r in Rubric.query.filter_by(workspace_id=ws.id, is_active=True).all()
    }
    created_ids: list[int] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        topic = str(raw.get("topic") or "").strip()
        if len(topic) < 3:
            continue
        code = str(raw.get("rubric_code") or "").strip()
        rubric = rubrics.get(code)
        post_type = rubric.code if rubric else (code or "expert")
        scheduled = str(raw.get("scheduled_for") or "").strip()
        note = str(raw.get("note") or "").strip()
        fmt = str(raw.get("format") or "").strip()
        materials = ""
        if note or fmt:
            materials = f"Формат: {fmt}\nПодсказка плана: {note}".strip()

        draft = Draft(
            user_id=user_id,
            workspace_id=ws.id,
            content_plan_id=content_plan_id,
            topic=topic[:300],
            post_type=post_type[:64],
            tone="",
            post_text="",
            status=sq.STATUS_PLANNED,
            scheduled_for=scheduled,
            materials_text=materials[:5000],
            generation_warning="",
        )
        db.session.add(draft)
        db.session.flush()
        created_ids.append(draft.id)

    if created_ids:
        db.session.commit()
    return created_ids


def regenerate_client_token(ws: Workspace) -> str:
    """Новая ссылка для клиента (старая перестанет работать)."""
    ws.client_approve_token = secrets.token_urlsafe(24)
    db.session.commit()
    return ws.client_approve_token


def plan_is_approved_for_draft(draft: Draft, ws: Workspace) -> tuple[bool, str]:
    """Если включено согласование плана — пост из плана можно публиковать только после approve."""
    if not bool(ws.require_client_approval):
        return True, "ok"
    if not draft.content_plan_id:
        return True, "ok"  # пост не из плана — согласование плана не требуется
    plan = db.session.get(ContentPlanBatch, draft.content_plan_id)
    if not plan:
        return True, "ok"
    if (plan.client_status or "") == "approved":
        return True, "ok"
    return False, "Контент-план ещё не согласован клиентом."


def apply_package_fields(ws: Workspace, *, code: str, custom_limit: int | None, require_approval: bool, auto_publish: bool) -> None:
    code = (code or "business").strip()
    if code not in PACKAGE_PRESETS:
        code = "business"
    ws.package_code = code
    if code == "custom":
        ws.package_posts_limit = max(0, int(custom_limit or 0))
    else:
        ws.package_posts_limit = int(PACKAGE_PRESETS[code]["limit"])
    if not (ws.package_period_start or "").strip():
        ws.package_period_start = date.today().replace(day=1).isoformat()
    ws.require_client_approval = bool(require_approval)
    ws.auto_publish_enabled = bool(auto_publish)
    ensure_client_token(ws)


def safe_log_api_usage(**kwargs) -> None:
    try:
        log_api_usage(**kwargs)
    except Exception:  # noqa: BLE001
        try:
            db.session.rollback()
        except Exception:  # noqa: BLE001
            pass


CLIENT_STATUS_LABELS = {
    "none": "—",
    "pending": "на согласовании",
    "approved": "согласован",
    "rejected": "отклонён",
}


def client_status_label(status: str | None) -> str:
    return CLIENT_STATUS_LABELS.get((status or "none").strip(), status or "—")


MONTH_NAMES_RU = (
    "",
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)


def month_title_ru(year: int, month: int) -> str:
    name = MONTH_NAMES_RU[month] if 1 <= month <= 12 else str(month)
    return f"{name} {year}"


def run_auto_publish_for_workspace(ws: Workspace) -> dict[str, Any]:
    """Публикует due-черновики канала. Возвращает счётчики."""
    import os

    from webapp.services import draft_visual as dv
    from webapp.services import vk_client

    if not bool(ws.auto_publish_enabled):
        return {"ok": False, "error": "Автопубликация выключена в настройках канала.", "published": 0, "errors": []}

    # Как при ручной публикации: канал → иначе .env
    token = (ws.vk_token or "").strip() or os.environ.get("VK_USER_TOKEN", "").strip() or os.environ.get(
        "VK_COMMUNITY_TOKEN", ""
    ).strip()
    group_id = (ws.vk_group_id or "").strip() or os.environ.get("VK_GROUP_ID", "").strip()
    if not token or not group_id:
        return {
            "ok": False,
            "error": "Нет VK токена или ID группы (в канале или в .env).",
            "published": 0,
            "errors": [],
        }

    due = due_auto_publish_drafts(ws)
    published = 0
    errors: list[str] = []
    for d in due:
        try:
            image_url, video_url = dv.resolve_publish_media(d)
            if not image_url and not video_url and not (d.post_text or "").strip():
                errors.append(f"#{d.id}: пустой пост")
                continue
            resp = vk_client.publish_draft(
                post_text=d.post_text,
                image_url=image_url,
                video_url=video_url,
                topic=d.topic,
                user_token=token,
                user_group_id=group_id,
            )
            post_id = resp.get("post_id")
            d.vk_post_id = str(post_id) if post_id is not None else ""
            d.status = sq.STATUS_PUBLISHED
            db.session.commit()
            published += 1
        except Exception as exc:  # noqa: BLE001
            try:
                db.session.rollback()
            except Exception:  # noqa: BLE001
                pass
            errors.append(f"#{d.id}: {exc}")
    return {
        "ok": True,
        "published": published,
        "checked": len(due),
        "errors": errors,
        "error": "",
    }
