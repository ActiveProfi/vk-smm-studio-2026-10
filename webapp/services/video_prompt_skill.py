"""
Скилл генерации видео для VK SMM.

Формула из библиотеки «Промпт для видео»: 6 блоков
объект → действие → место → камера → свет → стиль.

Пользователь кратко заполняет поля; приложение собирает полный промпт
и держит duration / aspect_ratio / негатив в отдельных параметрах заявки.
"""

from __future__ import annotations

from typing import Any

# Готовые варианты для выпадающих списков (из словарей скилла)
CAMERA_CHOICES: list[tuple[str, str]] = [
    ("", "— авто (приложение выберет)"),
    ("камера неподвижна, снято со штатива", "Неподвижная (штатив)"),
    ("камера медленно приближается", "Медленный наезд"),
    ("камера плавно отъезжает назад", "Отъезд назад"),
    ("камера панорамирует слева направо", "Панорама вправо"),
    ("камера следует за объектом сзади", "Следует сзади"),
    ("камера облетает объект по кругу", "Облёт по кругу"),
    ("камера снижается с высоты", "Снижение с высоты"),
    ("ручная камера с лёгкой тряской", "Ручная, лёгкая тряска"),
]

LIGHT_CHOICES: list[tuple[str, str]] = [
    ("", "— авто"),
    ("золотой час, низкое тёплое солнце", "Золотой час"),
    ("синий час, сумерки после заката", "Синий час"),
    ("мягкий рассеянный свет, пасмурно", "Мягкий пасмурный"),
    ("контровой свет, силуэт на просвет", "Контровой / силуэт"),
    ("контрастный боковой свет", "Боковой контрастный"),
    ("объёмный свет, лучи сквозь дым", "Лучи сквозь дым"),
    ("косой утренний свет, мягкие тени", "Утренний косой"),
    ("студийный мягкий свет, чистый фон", "Студийный"),
]

STYLE_CHOICES: list[tuple[str, str]] = [
    ("", "— авто"),
    ("предметная рекламная съёмка", "Реклама товара"),
    ("кинематографично, реалистичная физика", "Кинематограф"),
    ("документальная съёмка", "Документальный"),
    ("премиальная реклама, чистый кадр", "Премиум реклама"),
    ("живой темп, натуральные цвета", "Живой / натуральный"),
    ("скандинавский интерьер, спокойное движение", "Скандинавский"),
]

BRIEF_KEYS = (
    "object",
    "action",
    "place",
    "camera",
    "light",
    "style",
    "negative",
)

DEFAULT_CAMERA = "камера медленно приближается"
DEFAULT_LIGHT = "мягкий рассеянный свет, пасмурно"
DEFAULT_STYLE = "кинематографично, реалистичная физика"
DEFAULT_NEGATIVE = "текст, надписи, субтитры, логотипы, водяной знак"


def normalize_video_brief(raw: dict | None) -> dict[str, str]:
    """Достаёт и чистит поля брифа из формы / JSON."""
    data = raw if isinstance(raw, dict) else {}
    out: dict[str, str] = {}
    for key in BRIEF_KEYS:
        val = data.get(key) or data.get(f"video_{key}") or ""
        out[key] = str(val).strip()[:500]
    return out


def brief_has_content(brief: dict[str, str] | None) -> bool:
    if not brief:
        return False
    return bool(
        (brief.get("object") or "").strip()
        or (brief.get("action") or "").strip()
        or (brief.get("place") or "").strip()
    )


def build_video_prompt_from_brief(
    brief: dict[str, str],
    *,
    topic: str = "",
    channel_style: str = "",
    max_chars: int = 1400,
) -> str:
    """
    Собирает промпт по формуле 6 блоков.
    Пустые блоки добивает из темы / стиля канала / дефолтов скилла.
    """
    b = normalize_video_brief(brief)
    topic = (topic or "").strip()
    channel_style = (channel_style or "").strip()

    obj = b.get("object") or (f"сцена по теме «{topic}»" if topic else "главный объект сцены")
    action = b.get("action") or "мягко двигается в кадре"
    place = b.get("place") or "в подходящем окружении"
    camera = b.get("camera") or DEFAULT_CAMERA
    light = b.get("light") or DEFAULT_LIGHT
    style = b.get("style") or (
        channel_style[:180] if channel_style else DEFAULT_STYLE
    )

    # Одна фраза камеры / один стиль — без «седьмого блока»
    prompt = (
        f"{obj} {action} в {place}. "
        f"Камера: {camera}. "
        f"{light}. "
        f"{style}."
    )
    prompt += (
        " Без текста и надписей в кадре, без логотипов и водяных знаков. "
        "Одно движение камеры, один стиль."
    )

    if len(prompt) > max_chars:
        prompt = prompt[: max_chars - 1].rstrip() + "…"
    return prompt


def resolve_negative_prompt(brief: dict[str, str] | None) -> str:
    b = normalize_video_brief(brief)
    return (b.get("negative") or DEFAULT_NEGATIVE).strip()


def llm_video_skill_instructions(*, video_brief: dict[str, str] | None = None) -> str:
    """Текст для LLM: писать видеопромпт по скиллу."""
    lines = [
        "Скилл генерации видео (обязательно):\n"
        "Промпт видео = 6 блоков в одном абзаце 30–100 слов:\n"
        "[объект] [действие] в [место]. Камера [одно движение]. [Свет]. [Один стиль].\n"
        "Длительность и формат кадра НЕ писать в тексте — только в параметрах заявки.\n"
        "Не заказывай кириллический текст внутри кадра — надписи на монтаже.\n"
        "Одно движение камеры и один стиль на клип.\n"
    ]
    if brief_has_content(video_brief):
        b = normalize_video_brief(video_brief)
        lines.append("Пользователь уже задал краткий бриф — опирайся на него:\n")
        for label, key in (
            ("Объект / персонаж", "object"),
            ("Действие", "action"),
            ("Место", "place"),
            ("Камера", "camera"),
            ("Свет", "light"),
            ("Стиль", "style"),
            ("Запреты", "negative"),
        ):
            if b.get(key):
                lines.append(f"- {label}: {b[key]}\n")
        lines.append(
            "Дополни недостающие блоки сам, но не противоречь брифу пользователя.\n"
        )
    return "".join(lines)


def apply_video_brief_to_visual_data(
    visual_data: dict | None,
    video_brief: dict[str, str] | None,
    *,
    topic: str = "",
    channel_style: str = "",
    max_chars: int = 1400,
) -> dict | None:
    """
    Если пользователь заполнил бриф — подменяет / дополняет video_prompt_text
    структурированным промптом из скилла. Иначе visual_data не трогаем.
    """
    if not visual_data and not brief_has_content(video_brief):
        return visual_data

    vd: dict[str, Any] = dict(visual_data or {})
    if brief_has_content(video_brief):
        structured = build_video_prompt_from_brief(
            video_brief or {},
            topic=topic,
            channel_style=channel_style,
            max_chars=max_chars,
        )
        vd["video_prompt_text"] = structured
        # Для стартового кадра (image-to-video) короткий image-промпт можно оставить;
        # если картинки ещё нет — тот же структурный текст подойдёт как основа.
        if not (vd.get("image_prompt_text") or "").strip():
            vd["image_prompt_text"] = structured
        vd["visual_type"] = "video"
        vd["video_brief_applied"] = True
        vd["video_negative_prompt"] = resolve_negative_prompt(video_brief)
    return vd


def attach_negative_to_prompt_if_needed(
    video_prompt: str,
    negative: str,
    *,
    provider: str,
) -> str:
    """
    У части моделей нет отдельного поля негатива (Hailuo / часть Veo через KIE).
    Мягко дописываем запреты в конец текста, если их ещё нет.
    """
    prompt = (video_prompt or "").strip()
    neg = (negative or "").strip()
    if not prompt or not neg:
        return prompt
    # Kling / MiniMax через KIE сейчас не всегда принимают negative_prompt —
    # безопаснее держать запрет в тексте промпта одной короткой строкой.
    marker = "Запрещено в кадре:"
    if marker.lower() in prompt.lower() or neg.lower() in prompt.lower():
        return prompt
    extra = f"\n\n{marker} {neg}."
    if len(prompt) + len(extra) > 1400 and provider == "kling":
        return (prompt[: 1400 - len(extra) - 1].rstrip() + "…" + extra).strip()
    return (prompt + extra).strip()
