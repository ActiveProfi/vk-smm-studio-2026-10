"""ИИ-помощник для полей настроек канала."""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import run_agent as agent  # noqa: E402

ALLOWED_FIELDS = frozenset({"description", "knowledge_text", "visual_style_prompt"})

FIELD_LABELS = {
    "description": "Описание канала",
    "knowledge_text": "База знаний канала",
    "visual_style_prompt": "Промпт визуального стиля",
}


def _strip_markdown_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned.strip())
    return cleaned.strip()


def _build_user_message(
    field: str,
    *,
    name: str,
    theme: str,
    description: str,
    knowledge_text: str = "",
    brand_site: str = "",
    current_text: str,
    reference_names: str = "",
    reference_count: int = 0,
) -> str:
    label = FIELD_LABELS[field]
    rewrite_from_refs = field == "visual_style_prompt" and reference_count > 0
    if rewrite_from_refs:
        mode = "полностью пересоздай с нуля на основе приложенных референсов"
        current_block = ""
    else:
        mode = "улучши и дополни" if current_text.strip() else "создай с нуля"
        current_block = ""
        if current_text.strip():
            current_block = (
                f"\n\nТекущий текст поля «{label}» (исходник для доработки):\n"
                f"{current_text.strip()}\n"
            )

    common_context = (
        f"Название канала: {name or 'не указано'}\n"
        f"Тематика: {theme or 'не указана'}\n"
        f"Описание канала: {description or 'не указано'}\n"
    )
    if field == "visual_style_prompt":
        if (knowledge_text or "").strip():
            common_context += f"База знаний канала:\n{knowledge_text.strip()}\n"
        if (brand_site or "").strip():
            common_context += f"Бренд / сайт для подписи на визуалах: {brand_site.strip()}\n"

    ref_block = ""
    if rewrite_from_refs:
        names_line = reference_names or f"{reference_count} файлов"
        ref_block = (
            f"\nЗагруженные референсы стиля ({names_line}) приложены как картинки к этому сообщению.\n"
            "Главный источник палитры, композиции, типографики и настроения — именно эти референсы.\n"
            "Если среди референсов есть реальные фото людей или животных — зафиксируй в промпте стиля:\n"
            "сначала выбирать подходящее реальное фото; сохранять персонажа; менять сцену вокруг;\n"
            "другой ракурс — только другое реальное фото, не генеративный поворот.\n"
            "Если раньше был другой промпт стиля — полностью замени его, не сохраняй старую палитру.\n"
        )

    if field == "description":
        task = (
            f"Задача: {mode} **описание** VK-канала (2–4 предложения).\n"
            "Опиши: для кого канал, о чём публикуете, какой тон и цель.\n"
            "Пиши простым русским языком, без markdown, без заголовков и списков с «#».\n"
            "Не выдумывай конкретные цифры, законы и факты — только общая рамка канала."
        )
    elif field == "knowledge_text":
        task = (
            f"Задача: {mode} **базу знаний** для этого канала.\n"
            "Формат: короткие блоки с фактами, терминами, правилами и ограничениями для генерации постов.\n"
            "Можно использовать маркированные строки «- …», но без markdown-заголовков (#, ##).\n"
            "Если точных фактов нет — дай каркас с пометками «уточнить: …», не выдумывай нормы и цифры.\n"
            "Только тематика этого канала, без чужих тем."
        )
    else:
        task = (
            f"Задача: {mode} **промпт визуального стиля** для генерации картинок/инфографики этого канала.\n"
            "Опиши: палитру (можно HEX), фон, шрифты (крупная кириллица), композицию, настроение, что избегать.\n"
            "Если есть референсы — опирайся на их визуальный язык, но не копируй чужие логотипы и тексты.\n"
            "Обязательно впиши правило про реальные фото персонажей:\n"
            "- если среди референсов есть реальные фото людей или животных — сначала выбирать подходящее фото;\n"
            "- максимально сохранять лицо/тело персонажа, генеративно менять в основном фон и сцену;\n"
            "- другой ракурс — только через другое реальное фото из референсов, не «поворачивать» генерацией.\n"
            "Это инструкция для модели рисования, не текст поста.\n"
            "Без markdown, без URL, без англоязычных слов в смысловых надписях на картинке.\n"
            "5–12 строк, конкретно и по делу."
        )

    return (
        "Ты помогаешь настроить канал для SMM-кабинета. Ответ — только готовый текст для одного поля формы.\n\n"
        f"{common_context}"
        f"{ref_block}"
        f"{current_block}\n\n"
        f"{task}\n\n"
        "Верни **только** итоговый текст поля, без пояснений до и после."
    )


def _build_messages(user_message: str, reference_images: list[dict] | None) -> list[dict]:
    if not reference_images:
        return [{"role": "user", "content": user_message}]

    content: list[dict] = []
    for img in reference_images:
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img["media_type"],
                    "data": img["data_b64"],
                },
            }
        )
    content.append({"type": "text", "text": user_message})
    return [{"role": "user", "content": content}]


def _resolve_field_provider(field: str, reference_images: list[dict] | None) -> tuple[str, str]:
    """Для vision по референсам предпочитаем прямой Claude API."""
    if field == "visual_style_prompt" and reference_images:
        try:
            return agent.resolve_text_provider("anthropic")
        except ValueError:
            return agent.resolve_text_provider("kie")
    return agent.resolve_text_provider("kie")


def generate_workspace_field(
    field: str,
    *,
    name: str,
    theme: str = "",
    description: str = "",
    knowledge_text: str = "",
    brand_site: str = "",
    current_text: str = "",
    reference_images: list[dict] | None = None,
    reference_names: str = "",
) -> str:
    if field not in ALLOWED_FIELDS:
        raise ValueError(f"Неизвестное поле: {field}")
    name = (name or "").strip()
    if len(name) < 2:
        raise ValueError("Сначала укажите название канала (минимум 2 символа).")

    refs = reference_images or []
    user_message = _build_user_message(
        field,
        name=name,
        theme=(theme or "").strip(),
        description=(description or "").strip(),
        knowledge_text=(knowledge_text or "").strip(),
        brand_site=(brand_site or "").strip(),
        current_text=(current_text or "").strip(),
        reference_names=(reference_names or "").strip(),
        reference_count=len(refs),
    )
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 2500 if field == "knowledge_text" else 1200,
        "stream": False,
        "system": (
            "Отвечай только готовым текстом для поля формы на русском языке. "
            "Без markdown-обёрток, без JSON, без tool_use."
        ),
        "tool_choice": {"type": "none"},
        "messages": _build_messages(user_message, refs if field == "visual_style_prompt" else None),
    }
    provider, api_key = _resolve_field_provider(field, refs)
    response = agent.send_claude_request(payload, api_key, provider)
    text = _strip_markdown_fences(agent.extract_text_from_response(response))
    if not text:
        raise RuntimeError("Модель вернула пустой ответ.")
    return text


def generate_rubric_prompt(
    *,
    workspace_name: str,
    workspace_theme: str = "",
    workspace_description: str = "",
    knowledge_text: str = "",
    rubric_code: str = "",
    rubric_title: str = "",
    current_text: str = "",
) -> str:
    """ИИ-генерация / улучшение промпта рубрики для канала."""
    title = (rubric_title or "").strip()
    code = (rubric_code or "").strip()
    if len(title) < 2 and len(code) < 2:
        raise ValueError("Сначала укажите название рубрики или код (минимум 2 символа).")

    name = (workspace_name or "").strip() or "канал"
    theme = (workspace_theme or "").strip()
    description = (workspace_description or "").strip()
    knowledge = (knowledge_text or "").strip()
    current = (current_text or "").strip()
    mode = "улучши и дополни" if current else "создай с нуля"

    current_block = ""
    if current:
        current_block = (
            f"\n\nТекущий промпт рубрики (исходник для доработки):\n{current}\n"
        )

    knowledge_block = ""
    if knowledge:
        cut = knowledge if len(knowledge) <= 4000 else knowledge[:4000] + "\n…(обрезано)"
        knowledge_block = f"\nБаза знаний канала (учитывай тон и ограничения, не копируй целиком):\n{cut}\n"

    label = title or code
    user_message = (
        "Ты помогаешь настроить рубрику постов для SMM-кабинета VK.\n"
        "Ответ — только готовый текст промпта рубрики, без пояснений до и после.\n\n"
        f"Канал: {name}\n"
        f"Тематика канала: {theme or 'не указана'}\n"
        f"Описание канала: {description or 'не указано'}\n"
        f"Код рубрики: {code or 'не указан'}\n"
        f"Название рубрики: {title or 'не указано'}\n"
        f"{knowledge_block}"
        f"{current_block}\n"
        f"Задача: {mode} **промпт рубрики «{label}»**.\n\n"
        "Промпт должен инструктировать модель, как писать посты именно этой рубрики.\n"
        "Обязательно включи блоки:\n"
        "1) Задача рубрики (1–2 предложения).\n"
        "2) Тон и обращение к аудитории канала.\n"
        "3) Структура поста (нумерованный список шагов).\n"
        "4) Правила оформления для VK: короткие абзацы; заголовки/подзаголовки жирным через **…**;\n"
        "   чистый текст без markdown-заголовков #.\n"
        "5) Что можно / нельзя (по тематике канала, без выдуманных фактов и цифр).\n"
        "6) Краткие требования к визуалу этой рубрики (стиль картинки/видео в 3–6 пунктах):\n"
        "   композиция, тип кадра, кириллица в надписях, что избегать.\n"
        "7) Мягкий CTA или вопрос в конце поста.\n\n"
        "Пиши по-русски, конкретно под эту рубрику и тематику канала.\n"
        "Не подменяй рубрику «универсальным экспертным постом», если название другое.\n"
        "Верни только текст промпта."
    )

    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 2800,
        "stream": False,
        "system": (
            "Отвечай только готовым текстом промпта рубрики на русском языке. "
            "Без markdown-обёрток ```, без JSON, без tool_use."
        ),
        "tool_choice": {"type": "none"},
        "messages": [{"role": "user", "content": user_message}],
    }
    provider, api_key = agent.resolve_text_provider("kie")
    response = agent.send_claude_request(payload, api_key, provider)
    text = _strip_markdown_fences(agent.extract_text_from_response(response))
    if not text:
        raise RuntimeError("Модель вернула пустой ответ.")
    return text
