"""Готовит и запускает месячную генерацию VK-черновиков.

По умолчанию ничего не отправляет в KIE: только создает входные JSON и список команд.
Для реальной генерации используйте флаг --send.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLAN_JSON = PROJECT_ROOT / "output" / "vk_month_plan.json"
INPUTS_DIR = PROJECT_ROOT / "output" / "vk-month-inputs"
COMMANDS_FILE = PROJECT_ROOT / "output" / "vk-month-generation-commands.ps1"

FORMAT_TO_POST_TYPE = {
    "expert": "expert",
    "razbor": "razbor",
    "serial": "serial",
    "checklist": "checklist",
    "case": "case",
    "humor": "yumor",
    "calculation": "calculation",
    "law_review": "law_review",
    "poll": "poll",
}


def safe_filename(value: str) -> str:
    allowed = []
    for char in value:
        if char.isalnum() or char in (" ", "-", "_", "."):
            allowed.append(char)
        else:
            allowed.append("_")
    return "".join(allowed).strip(" ._")[:80] or "topic"


def build_input(plan_item: dict) -> dict:
    post_format = str(plan_item.get("post_format") or "razbor")
    post_type = FORMAT_TO_POST_TYPE.get(post_format, "razbor")
    topic = str(plan_item.get("topic") or "").strip()
    format_name = str(plan_item.get("format_name") or post_format).strip()
    section = str(plan_item.get("section") or "").strip()

    return {
        "post_type": post_type,
        "raw_materials": [
            f"Тема поста: {topic}",
            f"Раздел плана: {section}",
            f"Формат по месячному плану: {format_name}",
            "Сделать самостоятельный VK-пост для запланированной публикации.",
            "Текст должен быть понятным для бухгалтера и предпринимателя.",
            "Не выдумывать факты, ставки, сроки и юридические выводы: использовать только базу проекта.",
            "Для визуала подготовить понятную статичную картинку/инфографику под VK.",
        ],
        "sources_note": "knowledge/nds-2026-facts.md",
        "tone": "спокойно, профессионально, простым языком для бухгалтера и предпринимателя",
        "cta": "yes",
        "visual_intent": "image",
    }


def load_plan() -> list[dict]:
    if not PLAN_JSON.exists():
        raise FileNotFoundError(
            f"Не найден {PLAN_JSON}. Сначала запустите: py -3 tools/build_vk_month_plan.py"
        )
    plan = json.loads(PLAN_JSON.read_text(encoding="utf-8"))
    if not isinstance(plan, list) or not plan:
        raise ValueError("План месяца пустой или имеет неверный формат.")
    return plan


def write_inputs(plan: list[dict], *, limit: int | None) -> list[tuple[dict, Path]]:
    INPUTS_DIR.mkdir(parents=True, exist_ok=True)
    selected = plan[:limit] if limit else plan
    result: list[tuple[dict, Path]] = []

    for item in selected:
        day = int(item.get("day") or len(result) + 1)
        topic = safe_filename(str(item.get("topic") or f"day-{day}"))
        path = INPUTS_DIR / f"day-{day:02d} - {topic}.json"
        path.write_text(json.dumps(build_input(item), ensure_ascii=False, indent=2), encoding="utf-8")
        result.append((item, path))
    return result


def command_for(input_path: Path, scheduled_for: str) -> list[str]:
    return [
        sys.executable,
        str(PROJECT_ROOT / "run_agent.py"),
        "--input",
        str(input_path),
        "--send",
        "--send-image",
        "--draft-status",
        "ready",
        "--scheduled-for",
        scheduled_for,
    ]


def write_commands(items: list[tuple[dict, Path]]) -> None:
    lines = [
        "# Команды генерации месячных VK-черновиков",
        "# Запускать из корня проекта.",
        "",
    ]
    for item, input_path in items:
        scheduled_for = str(item["scheduled_for"])
        rel_input = input_path.relative_to(PROJECT_ROOT)
        lines.append(
            f'py -3 run_agent.py --input "{rel_input}" --send --send-image '
            f'--draft-status ready --scheduled-for "{scheduled_for}"'
        )
    COMMANDS_FILE.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Месячная генерация VK-черновиков.")
    parser.add_argument("--send", action="store_true", help="Реально отправлять запросы в KIE.")
    parser.add_argument("--limit", type=int, default=0, help="Сколько дней плана обработать. 0 = весь план.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plan = load_plan()
    items = write_inputs(plan, limit=args.limit or None)
    write_commands(items)

    print(f"Подготовлено входных файлов: {len(items)}")
    print(f"Папка: {INPUTS_DIR}")
    print(f"Команды: {COMMANDS_FILE}")

    if not args.send:
        print("KIE не запускали. Для генерации добавьте --send.")
        return 0

    for index, (item, input_path) in enumerate(items, start=1):
        scheduled_for = str(item["scheduled_for"])
        print(f"\n[{index}/{len(items)}] Генерация: {item.get('topic')} -> {scheduled_for}")
        completed = subprocess.run(command_for(input_path, scheduled_for), cwd=PROJECT_ROOT, check=False)
        if completed.returncode != 0:
            print(f"Остановка: run_agent.py вернул код {completed.returncode}", file=sys.stderr)
            return completed.returncode

    print("\nГотово: месячные черновики отправлены в Supabase со статусом ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
