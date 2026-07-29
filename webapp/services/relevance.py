"""Отдельный агент проверки актуальности фактов перед генерацией поста."""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import run_agent as agent  # noqa: E402


RELEVANCE_SYSTEM_TEMPLATE = """Ты — агент проверки актуальности данных для постов по теме: {theme}.
Твоя задача: проверить материалы пользователя и результаты веб-поиска.
Не пиши пост. Только отчёт.

Правила:
1. Сверь цифры, даты и формулировки с базой знаний канала (если она есть во входных данных).
2. Пометь устаревшее, сомнительное и неподтверждённое.
3. Если факта нет в базе канала и в надёжных источниках — пометь как «не подтверждено, не использовать».
4. Не подставляй факты из других тематик, если их нет во входных материалах.
5. Ответ строго в JSON без markdown:
{{
  "is_safe": true/false,
  "summary": "краткий вывод на русском",
  "approved_facts": ["..."],
  "outdated_or_risky": ["..."],
  "recommendations": ["..."]
}}
"""


def build_relevance_system(*, workspace_theme: str = "", topic: str = "") -> str:
    theme = (workspace_theme or topic or "указанная пользователем тема").strip()
    return RELEVANCE_SYSTEM_TEMPLATE.format(theme=theme)


def check_relevance(
    *,
    topic: str,
    materials: str,
    search_text: str,
    knowledge_excerpt: str,
    workspace_theme: str = "",
) -> dict:
    """
    Вызывает KIE/Claude как отдельного агента проверки актуальности.
    Возвращает dict с is_safe и отчётом.
    """
    user_message = (
        f"Тема: {topic}\n\n"
        f"=== Материалы пользователя ===\n{materials}\n\n"
        f"=== Веб-поиск ===\n{search_text or 'нет'}\n\n"
        f"=== База знаний канала (фрагмент) ===\n{knowledge_excerpt[:6000] or 'не заполнена'}\n"
    )

    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 2000,
        "stream": False,
        "system": build_relevance_system(workspace_theme=workspace_theme, topic=topic),
        "tool_choice": {"type": "none"},
        "messages": [{"role": "user", "content": user_message}],
    }

    provider, api_key = agent.resolve_text_provider("kie")
    response = agent.send_claude_request(payload, api_key, provider)
    text = agent.extract_text_from_response(response).strip()

    # Убрать возможные ```json обёртки
    cleaned = text
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        data = {
            "is_safe": False,
            "summary": "Не удалось разобрать ответ агента актуальности.",
            "approved_facts": [],
            "outdated_or_risky": [text[:500]],
            "recommendations": ["Повторите проверку или уточните материалы."],
            "raw": text,
        }

    if "is_safe" not in data:
        data["is_safe"] = False
    data["raw_text"] = text
    return data


def load_knowledge_excerpt() -> str:
    """Устаревший fallback — база знаний берётся только из канала."""
    return ""
