"""
Проверяет месячный VK-план и находит темы, где агенту нужны точные факты.

Выход:
- output/vk_fact_requests.json
- output/vk_fact_requests.md

Опционально сохраняет запросы в Supabase:
  py -3 tools/audit_vk_plan_facts.py --save-supabase

Перед --save-supabase один раз выполнить supabase_vk_content_intake.sql в Supabase SQL Editor.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from publish_vk_scheduled import supabase_request  # noqa: E402


PLAN_JSON = PROJECT_ROOT / "output" / "vk_month_plan.json"
RULES_JSON = PROJECT_ROOT / "configs" / "vk_fact_audit_rules.json"
REQUESTS_JSON = PROJECT_ROOT / "output" / "vk_fact_requests.json"
REQUESTS_MD = PROJECT_ROOT / "output" / "vk_fact_requests.md"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def match_rule(plan_item: dict, rule: dict) -> str | None:
    topic = (plan_item.get("topic") or "").lower()
    post_format = (plan_item.get("post_format") or "").lower()

    formats = [str(x).lower() for x in rule.get("formats", [])]
    if formats and post_format in formats:
        return rule["missing_fact"]

    keywords = [str(x).lower() for x in rule.get("keywords", [])]
    if keywords and any(keyword in topic for keyword in keywords):
        return rule["missing_fact"]

    return None


def build_fact_requests(plan: list[dict], rules: list[dict]) -> list[dict]:
    requests: list[dict] = []
    for item in plan:
        missing_facts: list[str] = []
        matched_rule_ids: list[str] = []
        for rule in rules:
            fact = match_rule(item, rule)
            if fact and fact not in missing_facts:
                missing_facts.append(fact)
                matched_rule_ids.append(rule["id"])

        if not missing_facts:
            continue

        requests.append(
            {
                "topic_id": item["topic_id"],
                "topic": item["topic"],
                "post_format": item["post_format"],
                "format_name": item["format_name"],
                "scheduled_for": item["scheduled_for"],
                "missing_facts": missing_facts,
                "why_needed": "В теме или формате есть точные утверждения/расчёты/правовые нюансы, которые нельзя додумывать.",
                "matched_rules": matched_rule_ids,
                "source_plan": item,
            }
        )
    return requests


def write_outputs(requests: list[dict]) -> None:
    REQUESTS_JSON.write_text(json.dumps(requests, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Запросы фактов для VK-плана",
        "",
        "Эти темы требуют дополнительных подтверждённых материалов перед генерацией постов.",
        "",
    ]
    if not requests:
        lines.append("Тем, требующих уточнения, не найдено.")
    for index, item in enumerate(requests, start=1):
        lines.extend(
            [
                f"## {index}. {item['topic']}",
                "",
                f"- ID темы: `{item['topic_id']}`",
                f"- Формат: {item['format_name']} (`{item['post_format']}`)",
                f"- Дата: {item['scheduled_for']}",
                "- Что нужно загрузить:",
            ]
        )
        for fact in item["missing_facts"]:
            lines.append(f"  - {fact}")
        lines.extend(["", ""])
    REQUESTS_MD.write_text("\n".join(lines), encoding="utf-8")


def save_to_supabase(requests: list[dict]) -> None:
    for item in requests:
        payload = {
            "status": "needs_materials",
            "topic_id": item["topic_id"],
            "topic": item["topic"],
            "post_format": item["post_format"],
            "scheduled_for": item["scheduled_for"],
            "missing_facts": item["missing_facts"],
            "why_needed": item["why_needed"],
            "source_plan": item["source_plan"],
            "notes": f"Создано аудитом фактов: {datetime.now(timezone.utc).isoformat()}",
        }
        supabase_request("POST", "vk_fact_requests", payload=payload)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Аудит VK-плана на нехватку точных фактов.")
    parser.add_argument("--save-supabase", action="store_true", help="Сохранить запросы в Supabase.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plan = load_json(PLAN_JSON)
    rules = load_json(RULES_JSON)["rules"]
    requests = build_fact_requests(plan, rules)
    write_outputs(requests)
    print(f"Тем в плане: {len(plan)}")
    print(f"Требуют фактов: {len(requests)}")
    print(f"Файл JSON: {REQUESTS_JSON}")
    print(f"Файл для чтения: {REQUESTS_MD}")

    if args.save_supabase:
        save_to_supabase(requests)
        print("Запросы фактов сохранены в Supabase: vk_fact_requests")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
