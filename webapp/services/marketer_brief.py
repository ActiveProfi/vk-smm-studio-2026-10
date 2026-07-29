"""ИИ-маркетолог канала: резюме для UI + правила для агентов «под капотом»."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import run_agent as agent  # noqa: E402


def _strip_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned.strip())
    return cleaned.strip()


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = _strip_fences(text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            raise ValueError("ИИ-маркетолог не вернул JSON.") from None
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("Ответ маркетолога должен быть JSON-объектом.")
    return data


def settings_ready_for_marketer(
    *,
    name: str,
    theme: str = "",
    description: str = "",
    knowledge_text: str = "",
    visual_style_prompt: str = "",
) -> tuple[bool, str]:
    """Минимум полей, чтобы собрать осмысленное резюме."""
    if len((name or "").strip()) < 2:
        return False, "Укажите название канала."
    if len((theme or "").strip()) < 2 and len((description or "").strip()) < 20:
        return False, "Заполните тематику или описание канала."
    if len((description or "").strip()) < 20 and len((knowledge_text or "").strip()) < 40:
        return False, "Добавьте описание или базу знаний (хотя бы кратко)."
    if len((visual_style_prompt or "").strip()) < 15:
        return False, "Заполните промпт визуального стиля (или сгенерируйте ИИ)."
    return True, ""


def build_marketer_settings_prompt(
    *,
    name: str,
    theme: str,
    description: str,
    brand_site: str,
    search_hint: str,
    knowledge_text: str,
    visual_style_prompt: str,
    reference_names: str = "",
    rubrics: list[dict[str, str]] | None = None,
) -> str:
    knowledge = (knowledge_text or "").strip()
    if len(knowledge) > 4000:
        knowledge = knowledge[:4000] + "\n…(обрезано)"
    style = (visual_style_prompt or "").strip()
    if len(style) > 2000:
        style = style[:2000] + "\n…(обрезано)"
    rubrics = rubrics or []
    rubrics_block = "\n".join(
        f"- {r.get('title') or r.get('code')}: {(r.get('prompt_hint') or '')[:160]}"
        for r in rubrics
    ) or "рубрики ещё не заданы"

    return (
        "Ты — ИИ-маркетолог SMM-агентства (только ВКонтакте).\n"
        "По настройкам канала сформируй:\n"
        "1) короткое резюме канала для менеджера (человекочитаемое);\n"
        "2) правила для других агентов «под капотом» — они не показываются клиенту как форма,\n"
        "   но обязаны соблюдаться при генерации.\n\n"
        "## Настройки канала\n"
        f"Название: {name}\n"
        f"Тематика: {theme or 'не указана'}\n"
        f"Описание: {description or 'не указано'}\n"
        f"Бренд/сайт: {brand_site or 'нет'}\n"
        f"Подсказка поиска: {search_hint or 'нет'}\n"
        f"Референсы стиля: {reference_names or 'нет'}\n"
        f"Промпт визуального стиля:\n{style or 'не задан'}\n"
        f"База знаний:\n{knowledge or 'не заполнена'}\n"
        f"Рубрики:\n{rubrics_block}\n\n"
        "## Верни ТОЛЬКО JSON\n"
        "{\n"
        '  "resume": "3–6 предложений: кто канал, для кого, оффер, тон, чем отличается",\n'
        '  "audience": "портрет аудитории VK: кто, боли, когда онлайн, интересы",\n'
        '  "copywriter_rules": "инструкции копирайтеру: тон, лексика, запреты, угол подачи под аудиторию",\n'
        '  "editor_rules": "инструкции редактору текста: как выделять заголовок и абзацы для VK '
        '(жирный через **…**, короткие абзацы, подзаголовки, воздух между блоками, что не делать)",\n'
        '  "visual_rules": "инструкции агенту картинок/видео: стиль, палитра, кириллица в «ёлочках», '
        'позыв/CTA на кадре, что писать на визуале, чего избегать; опирайся на visual_style и референсы"\n'
        "}\n\n"
        "Пиши по-русски, конкретно. Без markdown вокруг JSON. Не выдумывай законы и цифры."
    )


def generate_channel_marketer_brief(
    *,
    name: str,
    theme: str = "",
    description: str = "",
    brand_site: str = "",
    search_hint: str = "",
    knowledge_text: str = "",
    visual_style_prompt: str = "",
    reference_names: str = "",
    rubrics: list[dict[str, str]] | None = None,
) -> dict[str, str]:
    ok, err = settings_ready_for_marketer(
        name=name,
        theme=theme,
        description=description,
        knowledge_text=knowledge_text,
        visual_style_prompt=visual_style_prompt,
    )
    if not ok:
        raise ValueError(err)

    user_message = build_marketer_settings_prompt(
        name=name,
        theme=theme,
        description=description,
        brand_site=brand_site,
        search_hint=search_hint,
        knowledge_text=knowledge_text,
        visual_style_prompt=visual_style_prompt,
        reference_names=reference_names,
        rubrics=rubrics,
    )
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 3500,
        "stream": False,
        "system": (
            "Ты ИИ-маркетолог канала VK. "
            "Формируешь резюме и правила для копирайтера, редактора и визуал-агента. "
            "Ответ — только JSON. Без tool_use."
        ),
        "tool_choice": {"type": "none"},
        "messages": [{"role": "user", "content": user_message}],
    }
    provider, api_key = agent.resolve_text_provider("kie")
    response = agent.send_claude_request(payload, api_key, provider)
    text = agent.extract_text_from_response(response)
    data = _parse_json_object(text)

    resume = str(data.get("resume") or "").strip()
    audience = str(data.get("audience") or "").strip()
    copywriter = str(data.get("copywriter_rules") or "").strip()
    editor = str(data.get("editor_rules") or "").strip()
    visual = str(data.get("visual_rules") or "").strip()
    if not resume:
        raise ValueError("Маркетолог не вернул резюме канала.")
    if not (copywriter and editor and visual):
        raise ValueError("Маркетолог не вернул полный набор правил для агентов.")

    # Резюме для экрана: resume + audience
    resume_full = resume
    if audience:
        resume_full = f"{resume}\n\nАудитория: {audience}"

    rules = {
        "audience": audience,
        "copywriter_rules": copywriter,
        "editor_rules": editor,
        "visual_rules": visual,
    }
    return {
        "resume": resume_full[:6000],
        "rules_json": json.dumps(rules, ensure_ascii=False, indent=2),
        "audience": audience,
        "copywriter_rules": copywriter,
        "editor_rules": editor,
        "visual_rules": visual,
    }


def load_marketer_rules(workspace) -> dict[str, str]:
    raw = (getattr(workspace, "marketer_rules_json", None) or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "audience": str(data.get("audience") or "").strip(),
        "copywriter_rules": str(data.get("copywriter_rules") or "").strip(),
        "editor_rules": str(data.get("editor_rules") or "").strip(),
        "visual_rules": str(data.get("visual_rules") or "").strip(),
    }


def text_agent_guidance(workspace) -> str:
    """Блок правил для копирайтера + редактора (под капотом в генерации текста)."""
    rules = load_marketer_rules(workspace)
    if not rules:
        return ""
    parts = []
    if rules.get("audience"):
        parts.append("Аудитория канала (от ИИ-маркетолога):\n" + rules["audience"])
    if rules.get("copywriter_rules"):
        parts.append(
            "Правила копирайтера (обязательно):\n" + rules["copywriter_rules"]
        )
    if rules.get("editor_rules"):
        parts.append(
            "Правила редактора текста / оформления для VK (обязательно):\n"
            + rules["editor_rules"]
        )
    return "\n\n".join(parts).strip()


def visual_agent_guidance(workspace) -> str:
    """Доп. указания визуал-агенту от маркетолога (поверх visual_style_prompt)."""
    rules = load_marketer_rules(workspace)
    visual = rules.get("visual_rules") or ""
    return visual.strip()


def merge_visual_style(base_style: str, workspace) -> str:
    """Стиль канала + указания маркетолога для картинок/видео."""
    base = (base_style or "").strip()
    extra = visual_agent_guidance(workspace)
    if not extra:
        return base
    if not base:
        return "Указания ИИ-маркетолога по визуалу:\n" + extra
    return (
        base
        + "\n\nДополнительно — указания ИИ-маркетолога (аудитория, позыв, текст на кадре):\n"
        + extra
    )
