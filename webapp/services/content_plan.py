"""ИИ-маркетолог: контент-план + лучшее время публикации для VK-канала."""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import run_agent as agent  # noqa: E402

ALLOWED_DAYS = frozenset({7, 14, 21, 31})
DEFAULT_TZ = "+10:00"
DEFAULT_HOUR = 10
DEFAULT_MINUTE = 0

DEFAULT_POSTS_BY_DAYS = {
    7: 5,
    14: 10,
    21: 14,
    31: 20,
}


def _strip_markdown_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned.strip())
    return cleaned.strip()


def _extract_plan_payload(text: str) -> tuple[list[Any], dict[str, str]]:
    """Достаёт массив постов и мета (аудитория / логика времени)."""
    cleaned = _strip_markdown_fences(text)
    meta: dict[str, str] = {}
    data: Any = None
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}|\[[\s\S]*\]", cleaned)
        if not match:
            raise ValueError("ИИ-маркетолог не вернул JSON плана.") from None
        data = json.loads(match.group(0))

    items: list[Any]
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("audience_summary", "audience", "audience_portrait"):
            val = str(data.get(key) or "").strip()
            if val:
                meta["audience_summary"] = val[:800]
                break
        for key in ("timing_logic", "timing", "schedule_logic"):
            val = str(data.get(key) or "").strip()
            if val:
                meta["timing_logic"] = val[:800]
                break
        raw_items = data.get("items") or data.get("plan") or data.get("posts")
        if not isinstance(raw_items, list):
            raise ValueError("В JSON плана нет массива items/plan.")
        items = raw_items
    else:
        raise ValueError("JSON плана должен быть массивом или объектом с items.")
    return items, meta


def _default_posts_count(days: int) -> int:
    return DEFAULT_POSTS_BY_DAYS.get(days, max(3, days // 2))


def _scheduled_iso(d: date, hour: int = DEFAULT_HOUR, minute: int = DEFAULT_MINUTE) -> str:
    return f"{d.isoformat()}T{hour:02d}:{minute:02d}:00{DEFAULT_TZ}"


def _parse_item_date(raw: str | None, start: date, days: int) -> date | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        pass
    if value.isdigit():
        n = int(value)
        if 1 <= n <= days:
            return start + timedelta(days=n - 1)
    return None


def _parse_time(item: dict[str, Any]) -> tuple[int, int]:
    """Час и минуты из полей time / hour / minute."""
    hour = DEFAULT_HOUR
    minute = DEFAULT_MINUTE
    raw_time = str(item.get("time") or item.get("publish_time") or "").strip()
    if raw_time:
        m = re.match(r"^(\d{1,2}):(\d{2})$", raw_time)
        if m:
            hour = max(0, min(23, int(m.group(1))))
            minute = max(0, min(59, int(m.group(2))))
            return hour, minute
    try:
        if item.get("hour") is not None:
            hour = max(0, min(23, int(item["hour"])))
        if item.get("minute") is not None:
            minute = max(0, min(59, int(item["minute"])))
    except (TypeError, ValueError):
        pass
    return hour, minute


def normalize_plan_items(
    raw_items: list[Any],
    *,
    rubrics: list[dict[str, str]],
    start: date,
    days: int,
) -> list[dict[str, str]]:
    """Приводит ответ модели к единому формату для UI и календаря."""
    if not rubrics:
        raise ValueError("У канала нет активных рубрик. Сначала добавьте рубрики.")

    by_code = {r["code"]: r for r in rubrics}
    by_title = {r["title"].casefold(): r for r in rubrics}
    fallback = rubrics[0]
    end = start + timedelta(days=days - 1)
    result: list[dict[str, str]] = []
    used_slots: set[str] = set()

    for idx, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue
        topic = str(item.get("topic") or item.get("theme") or item.get("title") or "").strip()
        if len(topic) < 3:
            continue

        code = str(item.get("rubric_code") or item.get("code") or "").strip()
        title = str(item.get("rubric_title") or item.get("rubric") or "").strip()
        rubric = by_code.get(code) or by_title.get(title.casefold()) or fallback

        raw_date = item.get("date") or item.get("day") or item.get("publish_date")
        d = _parse_item_date(str(raw_date) if raw_date is not None else None, start, days)
        if d is None:
            slot = int(idx * max(1, days) / max(1, len(raw_items)))
            d = start + timedelta(days=min(days - 1, slot))
        if d < start:
            d = start
        if d > end:
            d = end

        hour, minute = _parse_time(item)
        iso_day = d.isoformat()
        slot_key = f"{iso_day}T{hour:02d}:{minute:02d}"
        guard = 0
        while slot_key in used_slots and guard < days * 4:
            # сдвигаем на 30 минут или на день
            minute += 30
            if minute >= 60:
                minute -= 60
                hour += 1
            if hour >= 22:
                hour = 9
                minute = 0
                d = start + timedelta(days=(d.toordinal() - start.toordinal() + 1) % days)
                iso_day = d.isoformat()
            slot_key = f"{iso_day}T{hour:02d}:{minute:02d}"
            guard += 1
        used_slots.add(slot_key)

        fmt = str(item.get("format") or item.get("post_format") or "пост").strip() or "пост"
        note = str(item.get("note") or item.get("idea") or item.get("hint") or "").strip()
        time_why = str(item.get("time_why") or item.get("timing_note") or "").strip()
        if time_why and time_why not in note:
            note = f"{note} · время: {time_why}".strip(" ·") if note else f"время: {time_why}"

        result.append(
            {
                "date": iso_day,
                "time": f"{hour:02d}:{minute:02d}",
                "scheduled_for": _scheduled_iso(d, hour, minute),
                "rubric_code": rubric["code"],
                "rubric_title": rubric["title"],
                "topic": topic[:300],
                "format": fmt[:80],
                "note": note[:500],
            }
        )

    if not result:
        raise ValueError("ИИ-маркетолог не вернул ни одной пригодной темы.")
    return result


def build_marketer_prompt(
    *,
    workspace_name: str,
    theme: str,
    description: str,
    knowledge_text: str,
    brand_site: str = "",
    search_hint: str = "",
    visual_style_prompt: str = "",
    rubrics: list[dict[str, str]],
    start: date,
    days: int,
    posts_count: int,
) -> str:
    rubrics_lines = "\n".join(
        f"- code=`{r['code']}` · название: {r['title']}"
        + (f" · суть: {(r.get('prompt_hint') or '')[:180]}" if r.get("prompt_hint") else "")
        for r in rubrics
    )
    knowledge = (knowledge_text or "").strip()
    if len(knowledge) > 3500:
        knowledge = knowledge[:3500] + "\n…(обрезано)"
    style = (visual_style_prompt or "").strip()
    if len(style) > 1200:
        style = style[:1200] + "\n…(обрезано)"

    end = start + timedelta(days=days - 1)
    return (
        "Ты — ИИ-маркетолог SMM-агентства. Специализация: только ВКонтакте.\n"
        "Задача: проанализировать канал и аудиторию, затем составить контент-план "
        "с лучшим временем публикации для максимального охвата.\n"
        "Ответ — ТОЛЬКО один JSON-объект (без markdown и пояснений снаружи).\n\n"
        "## Данные канала (анализируй полностью)\n"
        f"Название: {workspace_name or 'не указано'}\n"
        f"Тематика: {theme or 'не указана'}\n"
        f"Описание: {description or 'не указано'}\n"
        f"Сайт / бренд: {brand_site or 'не указан'}\n"
        f"Подсказка для поиска/позиционирования: {search_hint or 'нет'}\n"
        f"Визуальный стиль (кратко): {style or 'не задан'}\n"
        f"База знаний канала:\n{knowledge or 'не заполнена'}\n\n"
        "## Рубрики (используй ТОЛЬКО их code)\n"
        f"{rubrics_lines}\n\n"
        f"## Период плана\n"
        f"С {start.isoformat()} по {end.isoformat()} ({days} дней).\n"
        f"Нужно примерно {posts_count} постов (±1 допустимо).\n\n"
        "## Что сделать\n"
        "1) Составь портрет потенциальной аудитории VK (кто читает, когда онлайн, интересы).\n"
        "2) Выбери лучшие слоты публикации под эту аудиторию и тип контента "
        "(будни/выходные, утро/день/вечер; типичные пики VK в РФ: часто 9–11, 12–14, 18–21).\n"
        "3) Собери контент-план: темы, рубрики, форматы, подсказки к генерации поста.\n"
        "4) Для КАЖДОГО поста укажи date + time (лучшее время именно для этой темы/формата).\n\n"
        "## Формат JSON\n"
        "{\n"
        '  "audience_summary": "2–4 предложения: кто аудитория и когда она в VK",\n'
        '  "timing_logic": "1–3 предложения: общая логика выбора времени",\n'
        '  "items": [\n'
        "    {\n"
        '      "date": "YYYY-MM-DD",\n'
        '      "time": "HH:MM",\n'
        '      "rubric_code": "код из списка",\n'
        '      "topic": "конкретная тема поста",\n'
        '      "format": "пост | картинка | видео | карусель",\n'
        '      "note": "подсказка редактору: угол, крючок, CTA",\n'
        '      "time_why": "почему это время (кратко)"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Правила:\n"
        "1) Темы разные, без повторов; чередуй рубрики.\n"
        "2) Даты только внутри периода; не ставь всё на один день и один час.\n"
        "3) time обязательно в формате HH:MM (24 часа).\n"
        "4) Не выдумывай законы, цифры и факты — формулируй темы общо.\n"
        "5) Пиши по-русски. Только JSON."
    )


def generate_content_plan(
    *,
    workspace_name: str,
    theme: str = "",
    description: str = "",
    knowledge_text: str = "",
    brand_site: str = "",
    search_hint: str = "",
    visual_style_prompt: str = "",
    rubrics: list[dict[str, str]],
    days: int,
    posts_count: int | None = None,
    start_date: date | None = None,
) -> dict[str, Any]:
    """Запуск ИИ-маркетолога. Возвращает {items, audience_summary, timing_logic}."""
    if days not in ALLOWED_DAYS:
        raise ValueError("Допустимый период: 7, 14, 21 или 31 день.")
    if not rubrics:
        raise ValueError("У канала нет активных рубрик. Добавьте рубрики в настройках канала.")

    start = start_date or date.today()
    count = posts_count if posts_count and posts_count > 0 else _default_posts_count(days)
    count = max(3, min(count, days + 5))

    user_message = build_marketer_prompt(
        workspace_name=workspace_name,
        theme=theme,
        description=description,
        knowledge_text=knowledge_text,
        brand_site=brand_site,
        search_hint=search_hint,
        visual_style_prompt=visual_style_prompt,
        rubrics=rubrics,
        start=start,
        days=days,
        posts_count=count,
    )
    max_tokens = 5500 if days >= 21 else 4000
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": max_tokens,
        "stream": False,
        "system": (
            "Ты ИИ-маркетолог для VK. "
            "Анализируешь канал и аудиторию, составляешь контент-план и лучшее время постов. "
            "Отвечай только валидным JSON-объектом. Без tool_use."
        ),
        "tool_choice": {"type": "none"},
        "messages": [{"role": "user", "content": user_message}],
    }
    provider, api_key = agent.resolve_text_provider("kie")
    response = agent.send_claude_request(payload, api_key, provider)
    text = agent.extract_text_from_response(response)
    raw_items, meta = _extract_plan_payload(text)
    items = normalize_plan_items(raw_items, rubrics=rubrics, start=start, days=days)
    return {
        "items": items,
        "audience_summary": meta.get("audience_summary") or "",
        "timing_logic": meta.get("timing_logic") or "",
    }


def display_datetime(scheduled_for: str) -> str:
    """Человекочитаемая дата для таблицы."""
    raw = (scheduled_for or "").strip()
    if not raw:
        return "—"
    try:
        normalized = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        return dt.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return raw
