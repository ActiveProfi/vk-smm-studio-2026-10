"""
Строит тестовый месячный план VK по списку тем и циклу форматов.

Вход:
- 30 тем Базовые изменения НДС 2026.md
- configs/vk_schedule_month.json

Выход:
- Входящие материалы/vk_topics.json
- output/vk_month_plan.json
- output/vk_month_plan_preview.md
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOPICS_SOURCE = PROJECT_ROOT / "30 тем Базовые изменения НДС 2026.md"
SCHEDULE_CONFIG = PROJECT_ROOT / "configs" / "vk_schedule_month.json"
TOPICS_JSON = PROJECT_ROOT / "Входящие материалы" / "vk_topics.json"
PLAN_JSON = PROJECT_ROOT / "output" / "vk_month_plan.json"
PLAN_PREVIEW = PROJECT_ROOT / "output" / "vk_month_plan_preview.md"


def parse_timezone(value: str) -> timezone:
    match = re.fullmatch(r"([+-])(\d{2}):(\d{2})", value.strip())
    if not match:
        raise ValueError(f"Неверный timezone: {value}")
    sign, hours, minutes = match.groups()
    delta = timedelta(hours=int(hours), minutes=int(minutes))
    if sign == "-":
        delta = -delta
    return timezone(delta)


def parse_topics(markdown: str) -> list[dict]:
    topics: list[dict] = []
    current_section = "Без раздела"
    topic_re = re.compile(r"^\s*(\d+)\\?\.\s*(.+?)\s*$")

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("**") and line.endswith("**"):
            current_section = line.strip("*").strip()
            continue
        match = topic_re.match(line)
        if match:
            number = int(match.group(1))
            title = match.group(2).strip()
            topics.append(
                {
                    "id": f"nds-2026-{number:02d}",
                    "number": number,
                    "section": current_section,
                    "topic": title,
                    "materials": [title],
                    "source": str(TOPICS_SOURCE.relative_to(PROJECT_ROOT)),
                }
            )
            continue
        if not topics:
            current_section = line
        else:
            # Ненумерованные строки между темами считаем разделами.
            current_section = line
    return topics


def build_plan(topics: list[dict], config: dict) -> list[dict]:
    start_date = datetime.fromisoformat(config["start_date"]).date()
    publish_hour, publish_minute = [int(part) for part in config["publish_time"].split(":", 1)]
    tz = parse_timezone(config["timezone"])
    sequence = config["sequence"]
    format_names = config.get("format_names", {})

    plan: list[dict] = []
    for index, topic in enumerate(topics[: int(config["period_days"])], start=0):
        post_format = sequence[index % len(sequence)]
        scheduled = datetime.combine(
            start_date + timedelta(days=index),
            datetime.min.time().replace(hour=publish_hour, minute=publish_minute),
            tzinfo=tz,
        )
        plan.append(
            {
                "day": index + 1,
                "scheduled_for": scheduled.isoformat(),
                "topic_id": topic["id"],
                "topic": topic["topic"],
                "section": topic["section"],
                "post_format": post_format,
                "format_name": format_names.get(post_format, post_format),
                "status": "planned",
            }
        )
    return plan


def write_preview(plan: list[dict]) -> None:
    lines = [
        "# План VK на тестовый месяц",
        "",
        "| День | Дата/время | Формат | Тема |",
        "|---:|---|---|---|",
    ]
    for item in plan:
        lines.append(
            f"| {item['day']} | {item['scheduled_for']} | {item['format_name']} | {item['topic']} |"
        )
    PLAN_PREVIEW.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    if not TOPICS_SOURCE.exists():
        print(f"Не найден файл тем: {TOPICS_SOURCE}", file=sys.stderr)
        return 1

    config = json.loads(SCHEDULE_CONFIG.read_text(encoding="utf-8"))
    topics = parse_topics(TOPICS_SOURCE.read_text(encoding="utf-8"))
    if not topics:
        print("Не удалось извлечь темы из файла.", file=sys.stderr)
        return 1

    TOPICS_JSON.parent.mkdir(parents=True, exist_ok=True)
    PLAN_JSON.parent.mkdir(parents=True, exist_ok=True)

    TOPICS_JSON.write_text(json.dumps(topics, ensure_ascii=False, indent=2), encoding="utf-8")
    plan = build_plan(topics, config)
    PLAN_JSON.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    write_preview(plan)

    print(f"Тем: {len(topics)}")
    print(f"Планов: {len(plan)}")
    print(f"Список тем: {TOPICS_JSON}")
    print(f"План JSON: {PLAN_JSON}")
    print(f"План preview: {PLAN_PREVIEW}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
