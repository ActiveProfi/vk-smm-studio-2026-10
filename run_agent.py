import argparse
from datetime import datetime
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib import error, request


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "output"
ENV_FILE = PROJECT_ROOT / ".env"
KIE_CLAUDE_URL = "https://api.kie.ai/claude/v1/messages"
ANTHROPIC_CLAUDE_URL = "https://api.anthropic.com/v1/messages"
KIE_IMAGE_TASK_URL = "https://api.kie.ai/api/v1/jobs/createTask"
KIE_TASK_INFO_URL = "https://api.kie.ai/api/v1/jobs/recordInfo?taskId={task_id}"
KIE_VEO_GENERATE_URL = "https://api.kie.ai/api/v1/veo/generate"
KIE_VEO_INFO_URL = "https://api.kie.ai/api/v1/veo/record-info?taskId={task_id}"
KIE_FILE_BASE64_UPLOAD_URL = "https://kieai.redpandaai.co/api/file-base64-upload"
HAILUO_TEXT_MODEL = "hailuo/02-text-to-video-pro"
HAILUO_IMAGE_MODEL = "hailuo/02-image-to-video-pro"
KLING_VIDEO_MODEL = "kling-3.0/video"
MINIMAX_TEXT_MODEL = "minimax-h3/text-to-video"
MINIMAX_IMAGE_MODEL = "minimax-h3/image-to-video"

# Провайдеры видео в кабинете (KIE)
VIDEO_PROVIDERS = ("kling", "minimax", "veo", "hailuo")
VIDEO_PROVIDER_LABELS = {
    "kling": "Kling 3.0",
    "minimax": "MiniMax H3",
    "veo": "Veo 3.1",
    "hailuo": "Hailuo 02",
}
# Правило: реальные фото из референсов канала (люди / животные / персонажи)
REAL_PHOTO_REFERENCE_RULE = """
## Правило реальных фото из референсов (обязательно)

Если среди референсов канала есть реальные фотографии (особенно люди или животные):

1. Сначала выбери **наиболее подходящее реальное фото** под сцену поста (ракурс, эмоция, жест, план).
2. Это фото подаётся как `image_input` / референс: **максимально сохрани лицо, тело, характер персонажа** (человека или животного).
3. Генеративно редактируй в основном **окружающую сцену**, фон, реквизит, инфографику, свет — не «перерисовывай» человека с нуля.
4. Если нужен **совершенно другой ракурс** — сначала ищи **другое ваше реальное фото** с таким ракурсом среди референсов.
5. **Запрещено** «поворачивать», дорисовывать профиль/спину или менять лицо генерацией, если подходящего фото нет: выбери ближайший реальный кадр или сцену без персонажа / с силуэтом без подмены личности.
6. В промпте для KIE явно укажи: какой референс-фото использовать как основу персонажа и что менять только вокруг него.
""".strip()

REAL_PERSON_REFERENCE_UNAVAILABLE = "REAL_PERSON_REFERENCE_UNAVAILABLE"

# Подсказки, что в сцене нужен конкретный реальный персонаж (человек / животное)
_REAL_PERSON_HINT_RE = re.compile(
    r"(?i)"
    r"ксени|kseni|"
    r"женщин|девушк|мужчин|человек|портрет|селфи|лиц[аоеу]|персонаж|"
    r"бульдог|собак|п[её]с\b|кот\b|кошк|животн|"
    r"real\s*person|real\s*photo|сохрани\s*(лицо|человека|тело)|"
    r"максимально\s*сохрани"
)

_NO_PERSON_FALLBACK_LOCK = (
    "\n\nВАЖНО — FAIL-SAFE: реальный фото-референс персонажа недоступен внешней модели. "
    "НЕ изображай конкретного реального человека или животного. "
    "НЕ подменяй похожим лицом. Только сцена / предметы / инфографика без портрета. "
    f"Статус: {REAL_PERSON_REFERENCE_UNAVAILABLE}."
)


def append_real_photo_reference_rule(prompt_text: str, *, has_references: bool) -> str:
    """Добавляет правило реальных фото в image-промпт, если есть референсы."""
    text = (prompt_text or "").strip()
    if not has_references:
        return text
    if "Правило реальных фото" in text or "максимально сохрани лицо" in text.lower():
        return text
    return (text + "\n\n" + REAL_PHOTO_REFERENCE_RULE).strip()


class RealPersonReferenceUnavailableError(RuntimeError):
    """Реальный персонаж нужен, но generation reference не передан модели."""

    def __init__(self, message: str, *, person_label: str = "person"):
        super().__init__(message)
        self.code = REAL_PERSON_REFERENCE_UNAVAILABLE
        self.person_label = person_label


MARKET_VIDEO_MODELS = {
    HAILUO_TEXT_MODEL,
    HAILUO_IMAGE_MODEL,
    KLING_VIDEO_MODEL,
    MINIMAX_TEXT_MODEL,
    MINIMAX_IMAGE_MODEL,
}
KIE_IMAGE_MODEL = "gpt-image-2-text-to-image"
KIE_IMAGE_TO_IMAGE_MODEL = "gpt-image-2-image-to-image"
KIE_IMAGE_MODEL_LABEL = "GPT Image 2"
KIE_IMAGE_TO_IMAGE_LABEL = "GPT Image 2 (image-to-image)"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0 Safari/537.36"
)

PROMPT_BY_TYPE = {
    "expert": PROJECT_ROOT / "prompts" / "expert.md",
    "razbor": PROJECT_ROOT / "prompts" / "razbor.md",
    "yumor": PROJECT_ROOT / "prompts" / "yumor.md",
    "serial": PROJECT_ROOT / "prompts" / "serial.md",
    "checklist": PROJECT_ROOT / "prompts" / "checklist.md",
    "case": PROJECT_ROOT / "prompts" / "case.md",
    "calculation": PROJECT_ROOT / "prompts" / "calculation.md",
    "law_review": PROJECT_ROOT / "prompts" / "law_review.md",
    "poll": PROJECT_ROOT / "prompts" / "poll.md",
    "article_announcement": PROJECT_ROOT / "prompts" / "article_announcement.md",
}

EXTRA_FILES_BY_TYPE = {
    "serial": [
        PROJECT_ROOT / "docs" / "characters" / "alina.md",
        PROJECT_ROOT / "prompts" / "serial-comic-frames.md",
    ]
}

COMMON_CONTEXT_FILES = [
    PROJECT_ROOT / "prompts" / "base-system-kie.md",
    PROJECT_ROOT / "knowledge" / "nds-2026-facts.md",
    PROJECT_ROOT / "docs" / "models" / "kie-text-model.md",
    PROJECT_ROOT / "docs" / "models" / "kie-visual-rules.md",
    PROJECT_ROOT / "docs" / "workflows" / "visual-decision.md",
]

REQUIRED_FIELDS = [
    "post_type",
    "raw_materials",
    "sources_note",
    "tone",
    "cta",
    "visual_intent",
]

VISUAL_FORBIDDEN_PHRASES = [
    "вычет есть",
    "вычет ограничен",
    "вычет входящего ндс",
    "вычет ндс",
    "ндс — нет",
    "без штрафов",
    "гарантия",
    "точно выгоднее",
    "всегда выгодно",
    "плати меньше",
    "налог будет меньше",
]

UNCONFIRMED_TEXT_MARKERS = [
    "2025",
    "ТН ВЭД",
    "ОКПД2",
    "письмо ФНС",
]

VISUAL_SAFE_SUGGESTIONS = [
    "22 процента или 5 процентов?",
    "Считать надо глубже",
    "Сравнивайте не только ставку",
    "Выбор ставки НДС",
    "НДС: считайте всю нагрузку",
]

VIDEO_TEXT_MARKERS = [
    "text overlay",
    "overlay text",
    "title card",
    "subtitle",
    "caption",
    "end frame",
    "bold yellow text",
    "текст в кадре",
    "текст на экране",
    "надпись",
    "субтитр",
]

# Допустимая латиница в надписях на картинке: названия сервисов и привычные суффиксы.
OVERLAY_LATIN_WHITELIST_PATTERNS = [
    r"яндекс\s*gpt",
    r"yandex\s*gpt",
    r"yandex",
    r"яндекс",
    r"chat\s*gpt",
    r"kandinsky",
    r"кandinsky",
    r"\bgpt\b",
    r"\bai\b",
    r"\bapi\b",
    r"\bpro\b",
    r"\bmax\b",
    r"\bmini\b",
    r"\bplus\b",
    r"\bvk\b",
    r"\bsmm\b",
    r"kling",
    r"hailuo",
    r"\bveo\b",
    r"open\s*ai",
    r"midjourney",
    r"stable\s*diffusion",
    r"\bgemini\b",
    r"\bclaude\b",
    r"\bsora\b",
    r"canva",
    r"шедеврум",
    r"shedevrum",
    r"gigachat",
    r"giga\s*chat",
    r"giga\s*чат",
    r"sber",
    r"сбер",
    r"deepseek",
    r"copilot",
    r"co\s*pilot",
    r"perplexity",
    r"notion",
    r"figma",
    r"quizlet",
    r"\bmiro\b",
    r"genially",
    r"mentimeter",
    r"magnific",
    r"storyboard",
    r"infourok",
    r"formatta",
    r"ispring",
    r"word\s*press",
    r"wordpress",
    r"\bpdf\b",
    r"\bpptx?\b",
    r"\bhtml\b",
    r"\bcss\b",
    r"\bzoom\b",
    r"\bteams\b",
    r"\bexcel\b",
    r"\bpowerpoint\b",
]

# Если бренд не в whitelist — подмена кириллицей в надписях на картинке (запасной вариант).
OVERLAY_LATIN_TRANSLITERATIONS: list[tuple[str, str]] = [
    (r"\bCanva\b", "Канва"),
    (r"\bNotion\b", "Ноушн"),
    (r"\bZoom\b", "Зум"),
    (r"\bFigma\b", "Фигма"),
    (r"\bMiro\b", "Миро"),
]


def _sanitize_overlay_chunk(chunk: str) -> str:
    out = chunk
    for pattern, replacement in OVERLAY_LATIN_TRANSLITERATIONS:
        out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)
    return out


def sanitize_visual_prompt_overlays(prompt_text: str) -> str:
    """Подготовка надписей «...» и \"...\" перед валидацией/генерацией."""

    def _angle(m: re.Match[str]) -> str:
        return "«" + _sanitize_overlay_chunk(m.group(1)) + "»"

    def _quote(m: re.Match[str]) -> str:
        return '"' + _sanitize_overlay_chunk(m.group(1)) + '"'

    text = re.sub(r"«([^»]+)»", _angle, prompt_text or "")
    return re.sub(r'"([^"]+)"', _quote, text)


def sanitize_visual_prompt_symbols(prompt_text: str) -> str:
    """
    Убирает символы, которые ломают image-валидацию, но часто встречаются
    в описании стиля (→ в «было → стало», имена файлов, URL).
    """
    text = prompt_text or ""
    replacements = (
        ("↔", " графическая двусторонняя стрелка-линия "),
        ("→", " графическая стрелка-линия вправо "),
        ("←", " графическая стрелка-линия влево "),
        ("⇒", " графическая стрелка-линия вправо "),
        ("⇐", " графическая стрелка-линия влево "),
        ("➜", " графическая стрелка-линия "),
        ("➡", " графическая стрелка-линия "),
        ("⟶", " графическая стрелка-линия "),
    )
    for src, dst in replacements:
        text = text.replace(src, dst)

    text = re.sub(r"https?://\S+|www\.\S+", " ", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\b[\w.\-]+\.(?:xlsx?|docx?|pptx?|pdf|png|jpe?g|gif|webp|mp4|mov)\b",
        "файл",
        text,
        flags=re.IGNORECASE,
    )
    text = text.replace("%", " процентов ")
    for ch in "$€£₽×−÷=+":
        text = text.replace(ch, " ")

    def _drop_latin_quote(m: re.Match[str]) -> str:
        inner = m.group(1)
        if re.search(r"[A-Za-z]", inner):
            return ""
        return m.group(0)

    text = re.sub(r"«([^»]+)»", _drop_latin_quote, text)
    text = re.sub(r'"([^"]+)"', _drop_latin_quote, text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def validate_and_prepare_image_visual_data(
    visual_data: dict,
    *,
    brand_footer: str = "",
) -> tuple[dict, dict]:
    """
    Проверка image-промпта. Если блокирует только латиница в надписях
    или символы стрелок — санитизация и повторная проверка.
    """
    vd = dict(visual_data)
    # Сразу чистим стрелки из описания стиля / сцены — это не «текст на картинке»
    vd["prompt_text"] = sanitize_visual_prompt_symbols(vd.get("prompt_text", ""))
    report = validate_visual_prompt(vd, brand_footer=brand_footer)
    if report.get("is_safe"):
        return vd, report

    errors = report.get("errors") or []
    latin_only = bool(errors) and all("латиница" in err for err in errors)
    if latin_only:
        vd["prompt_text"] = sanitize_visual_prompt_overlays(vd.get("prompt_text", ""))
        report2 = validate_visual_prompt(vd, brand_footer=brand_footer)
        if report2.get("is_safe"):
            return vd, report2
        return vd, report2
    return vd, report


def _overlay_text_without_allowed_latin(chunk: str, brand: str = "") -> str:
    """Убираем из фразы на картинке известные бренды/сервисы, потом ищем лишнюю латиницу."""
    cleaned = chunk
    if brand:
        cleaned = re.sub(re.escape(brand), "", cleaned, flags=re.IGNORECASE)
    for pattern in OVERLAY_LATIN_WHITELIST_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    return cleaned


def configure_console() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def load_dotenv_file() -> None:
    if not ENV_FILE.exists():
        return

    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value


def get_api_key() -> str:
    load_dotenv_file()
    api_key = os.environ.get("KIE_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "Не найден KIE_API_KEY. "
            "Добавьте его в переменную среды или в локальный файл .env."
        )
    return api_key


def get_anthropic_api_key() -> str:
    load_dotenv_file()
    for key_name in ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "ANTHROPIC_KEY"):
        api_key = os.environ.get(key_name, "").strip()
        if api_key:
            return api_key
    return ""


def resolve_text_provider(requested_provider: str) -> tuple[str, str]:
    if requested_provider not in {"auto", "anthropic", "kie"}:
        raise ValueError(f"Неизвестный text provider: {requested_provider}")

    anthropic_key = get_anthropic_api_key()
    if requested_provider == "anthropic":
        if not anthropic_key:
            raise ValueError(
                "Не найден прямой ключ Claude. "
                "Добавьте в .env переменную ANTHROPIC_API_KEY или CLAUDE_API_KEY."
            )
        return "anthropic", anthropic_key

    if requested_provider == "auto" and anthropic_key:
        return "anthropic", anthropic_key

    return "kie", get_api_key()


def _relative_project_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def try_log_agent_run_to_supabase(
    *,
    post_type: str,
    input_path: Path,
    input_data: dict,
    send_image: bool,
    send_video: bool,
    output_files: dict[str, str],
) -> None:
    """Опционально: одна строка в agent_runs, если в .env есть Supabase."""
    load_dotenv_file()
    base = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not base or not key:
        return

    row = {
        "post_type": post_type,
        "input_path": _relative_project_path(input_path),
        "input_data": input_data,
        "send_image": send_image,
        "send_video": send_video,
        "output_files": output_files,
    }
    rest_url = f"{base}/rest/v1/agent_runs"
    body = json.dumps(row, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        rest_url,
        data=body,
        method="POST",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Prefer": "return=minimal",
        },
    )
    try:
        with request.urlopen(req, timeout=45) as resp:
            if resp.status not in (200, 201, 204):
                print(
                    f"Supabase: неожиданный HTTP {resp.status} при записи журнала.",
                    file=sys.stderr,
                )
    except Exception as exc:  # noqa: BLE001
        print(
            f"Supabase: журнал не записан (продолжаем без ошибки): {exc}",
            file=sys.stderr,
        )
    else:
        print("Supabase: запись в agent_runs добавлена.")


def _extract_topic_for_draft(input_data: dict) -> str:
    raw_materials = input_data.get("raw_materials", [])
    if not isinstance(raw_materials, list) or not raw_materials:
        return ""

    first_item = str(raw_materials[0]).strip()
    first_item = re.sub(r"^Тема поста:\s*", "", first_item, flags=re.IGNORECASE)
    return first_item.strip()


def normalize_scheduled_for(value: str | None) -> str | None:
    if not value:
        return None

    cleaned = value.strip()
    if not cleaned:
        return None

    normalized = cleaned.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            "Неверный формат --scheduled-for. "
            "Пример: 2026-04-27T10:30:00+10:00"
        ) from exc
    return parsed.isoformat()


def resolve_vk_draft_status(
    requested_status: str,
    visual_data: dict | None,
    image_url: str | None,
    video_url: str | None,
) -> tuple[str, str]:
    """
    Для VK готовым считаем только комплект: текст + визуал.
    Если визуала нет, черновик принудительно остаётся draft.
    """
    if requested_status != "ready":
        return "draft", ""

    visual_type = ""
    if isinstance(visual_data, dict):
        visual_type = str(visual_data.get("visual_type", "")).strip()

    if visual_type == "image":
        if image_url:
            return "ready", ""
        return (
            "draft",
            "Статус автоматически оставлен draft: для VK нужен комплект текст + изображение.",
        )

    if visual_type == "video":
        if video_url:
            return "ready", ""
        return (
            "draft",
            "Статус автоматически оставлен draft: для VK нужен комплект текст + видео/анимация.",
        )

    return (
        "draft",
        "Статус автоматически оставлен draft: в ответе не найден подтверждённый визуал для VK.",
    )


def try_save_vk_draft_to_supabase(
    *,
    input_data: dict,
    post_text: str,
    visual_data: dict | None,
    image_url: str | None,
    video_url: str | None,
    draft_status: str,
    scheduled_for: str | None,
    output_files: dict[str, str],
) -> None:
    """Опционально: сохраняет готовый черновик поста в vk_drafts."""
    load_dotenv_file()
    base = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not base or not key:
        return

    visual_type = ""
    if isinstance(visual_data, dict):
        visual_type = str(visual_data.get("visual_type", "")).strip()

    final_status, notes = resolve_vk_draft_status(
        draft_status,
        visual_data,
        image_url,
        video_url,
    )

    row = {
        "status": final_status,
        "publish_channel": "vk",
        "topic": _extract_topic_for_draft(input_data),
        "post_type": input_data.get("post_type", ""),
        "post_text": post_text,
        "visual_type": visual_type or None,
        "image_url": image_url or None,
        "video_url": video_url or None,
        "notes": notes or None,
        "scheduled_for": scheduled_for,
        "input_data": input_data,
        "output_files": output_files,
    }
    rest_url = f"{base}/rest/v1/vk_drafts"
    body = json.dumps(row, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        rest_url,
        data=body,
        method="POST",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Prefer": "return=minimal",
        },
    )
    try:
        with request.urlopen(req, timeout=45) as resp:
            if resp.status not in (200, 201, 204):
                print(
                    f"Supabase: неожиданный HTTP {resp.status} при записи черновика VK.",
                    file=sys.stderr,
                )
    except Exception as exc:  # noqa: BLE001
        print(
            f"Supabase: черновик VK не записан (продолжаем без ошибки): {exc}",
            file=sys.stderr,
        )
    else:
        print("Supabase: черновик VK добавлен в vk_drafts.")
        if final_status != draft_status and notes:
            print(f"VK draft: {notes}")


def make_json_request(
    url: str,
    api_key: str,
    payload: dict | None = None,
    method: str = "POST",
    extra_headers: dict | None = None,
) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": DEFAULT_USER_AGENT,
    }
    if extra_headers:
        headers.update(extra_headers)

    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = request.Request(
        url,
        data=body,
        method=method,
        headers=headers,
    )

    try:
        with request.urlopen(req, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"HTTP {exc.code} при вызове KIE: {error_body}"
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(f"Ошибка сети при вызове KIE: {exc}") from exc


def load_input(input_path: Path) -> dict:
    data = json.loads(input_path.read_text(encoding="utf-8"))

    missing_fields = [field for field in REQUIRED_FIELDS if field not in data]
    if missing_fields:
        raise ValueError(
            "В JSON не хватает полей: " + ", ".join(missing_fields)
        )

    post_type = data["post_type"]
    # custom_prompt — рубрика канала из веб-приложения (свой текст промпта)
    if post_type not in PROMPT_BY_TYPE and not str(data.get("custom_prompt") or "").strip():
        raise ValueError(
            "Неизвестный post_type: "
            f"{post_type}. Допустимо: {', '.join(PROMPT_BY_TYPE)}"
        )

    if not isinstance(data["raw_materials"], list) or not data["raw_materials"]:
        raise ValueError("Поле raw_materials должно быть непустым списком.")

    return data


def format_input_block(data: dict) -> str:
    raw_materials = "\n".join(f"- {item}" for item in data["raw_materials"])
    rubric_title = str(data.get("rubric_title") or "").strip()

    lines = [
        "## Входные данные пользователя\n",
        f"- post_type (код рубрики): {data['post_type']}",
    ]
    if rubric_title:
        lines.append(f"- rubric_title (название рубрики): {rubric_title}")
    lines.extend(
        [
            f"- sources_note: {data['sources_note']}",
            f"- tone: {data['tone']}",
            f"- cta: {data['cta']}",
            f"- visual_intent: {data['visual_intent']}",
            "",
            "### raw_materials",
            raw_materials,
        ]
    )
    return "\n".join(lines)


def build_user_message(data: dict) -> str:
    sections = []
    custom_prompt = str(data.get("custom_prompt") or "").strip()
    workspace_theme = str(data.get("workspace_theme") or "").strip()
    workspace_knowledge = str(data.get("workspace_knowledge") or "").strip()
    brand_site = str(data.get("brand_site") or "").strip()
    visual_style_prompt = str(data.get("visual_style_prompt") or "").strip()
    reference_image_urls = [
        str(u).strip()
        for u in (data.get("reference_image_urls") or [])
        if str(u).strip()
    ][:8]
    reference_image_names = [
        str(n).strip()
        for n in (data.get("reference_image_names") or [])
        if str(n).strip()
    ][:8]
    rubric_title = str(data.get("rubric_title") or "").strip()
    post_type = str(data.get("post_type") or "").strip()

    # У Claude в KIE для v1 используем один user-блок,
    # поэтому системные правила и контекст склеиваем в одно сообщение.
    if custom_prompt:
        # Рубрика — главный закон стиля текста и картинки
        sections.append(
            "# ПРИОРИТЕТ 1 — РУБРИКА (обязательно следовать)\n\n"
            f"- Код рубрики: `{post_type}`\n"
            f"- Название рубрики: **{rubric_title or post_type}**\n\n"
            "## Жёсткие правила приоритета\n\n"
            "1. Структура, тон, логика и длина текста — **только** по промпту рубрики ниже.\n"
            "2. Стиль и композиция визуала (картинка/видео) — **только** по правилам визуала этой рубрики.\n"
            "3. Не подменяй рубрику «универсальным экспертным постом» или «стандартной NotebookLM-инфографикой», "
            "если рубрика требует иной формат (разбор, чек-лист, кейс, юмор, сериал, опрос и т.д.).\n"
            "4. Общие правила VK и база знаний ниже — вспомогательные: факты и UX ленты. "
            "Если они конфликтуют со стилем рубрики — **побеждает рубрика** "
            "(кроме запрета выдумывать факты).\n"
            "5. В блоке «Почему выбран такой формат» явно напиши, как текст и визуал соответствуют рубрике "
            f"`{rubric_title or post_type}`.\n\n"
            "## Промпт рубрики\n\n"
            f"{custom_prompt}"
        )

        base_path = PROJECT_ROOT / "prompts" / "base-system-kie.md"
        if base_path.exists():
            sections.append(
                "# ПРИОРИТЕТ 2 — Общие правила VK (вспомогательно)\n\n"
                "Используй из этого файла только: язык, запрет выдумывать факты, UX ленты VK, "
                "чистый текст без markdown (#, обратные кавычки), обязательные **заголовки** в блоке «Черновик поста», "
                "Стиль конкретной рубрики и стиль картинки бери из ПРИОРИТЕТА 1.\n\n"
                f"{read_text(base_path)}"
            )

        visual_rules = PROJECT_ROOT / "docs" / "models" / "kie-visual-rules.md"
        if visual_rules.exists():
            sections.append(
                "# ПРИОРИТЕТ 2б — Техпараметры визуальных моделей (не стиль рубрики)\n\n"
                "Отсюда бери только технические параметры моделей (aspect_ratio, resolution, Kling/Image 2). "
                "Художественный и смысловой стиль кадра — из промпта рубрики.\n\n"
                f"{read_text(visual_rules)}"
            )

        if visual_style_prompt or reference_image_urls or reference_image_names:
            ref_lines = ""
            if reference_image_names:
                ref_lines += (
                    "Загруженные референсы канала (палитра + реальные кадры персонажей): "
                    + ", ".join(reference_image_names[:8])
                    + ".\n"
                )
            if reference_image_urls:
                ref_lines += "URL референсов:\n" + "\n".join(
                    f"- {url}" for url in reference_image_urls[:8]
                ) + "\n"
            photo_rule_block = ""
            if reference_image_urls or reference_image_names:
                photo_rule_block = "\n\n" + REAL_PHOTO_REFERENCE_RULE + "\n"
            sections.append(
                "# Визуальный стиль канала (постоянные правила для картинки/видео)\n\n"
                "Эти правила задают фирменный стиль **этого канала**. "
                "Применяй их в промпте для KIE и в рекомендации по визуалу. "
                "Если стиль канала конфликтует с рубрикой — **побеждает рубрика** по структуре поста, "
                "но палитра, шрифты и общая эстетика берутся отсюда.\n\n"
                f"{visual_style_prompt or 'Промпт визуального стиля не задан — опирайся на рубрику.'}\n\n"
                f"{ref_lines}"
                f"{photo_rule_block}".rstrip()
            )

        if workspace_theme or brand_site:
            footer_rule = (
                f"- Подпись внизу визуала: `{brand_site}` — добавь маленьким текстом строго по центру внизу.\n"
                if brand_site
                else "- Подпись внизу визуала: не задана — не выдумывай сайт и не добавляй чужой адрес.\n"
            )
            sections.append(
                "# Контекст канала\n\n"
                f"- Тематика: {workspace_theme or 'не указана'}\n"
                f"{footer_rule}"
            )

        if workspace_knowledge:
            # База знаний — только факты, не стиль
            knowledge_cut = workspace_knowledge
            if len(knowledge_cut) > 8000:
                knowledge_cut = knowledge_cut[:8000] + "\n\n…(база знаний обрезана)"
            sections.append(
                "# База знаний канала (только факты, не стиль текста/картинки)\n\n"
                "Не копируй отсюда тон «экспертного поста», если выбранная рубрика другая. "
                "Бери только проверенные факты, цифры и нормы.\n\n"
                f"{knowledge_cut}"
            )
    else:
        for path in COMMON_CONTEXT_FILES:
            sections.append(f"# Файл: {path.relative_to(PROJECT_ROOT)}\n\n{read_text(path)}")

        prompt_path = PROMPT_BY_TYPE[data["post_type"]]
        sections.append(
            f"# Файл: {prompt_path.relative_to(PROJECT_ROOT)}\n\n{read_text(prompt_path)}"
        )

        for extra_path in EXTRA_FILES_BY_TYPE.get(data["post_type"], []):
            sections.append(
                f"# Файл: {extra_path.relative_to(PROJECT_ROOT)}\n\n{read_text(extra_path)}"
            )

    sections.append(format_input_block(data))
    rubric_label = rubric_title or post_type or data.get("post_type", "")
    sections.append(
        "## Финальная инструкция\n\n"
        f"Собери ответ строго под рубрику **{rubric_label}**.\n"
        "1. Черновик поста — структура и тон как в промпте рубрики. "
        "Первая строка — **главный заголовок**, дальше перед каждым блоком/новой мыслью — **подзаголовок** отдельной строкой.\n"
        "2. В «Почему выбран такой формат» укажи соответствие рубрике.\n"
        "3. Рекомендация image/video — по правилам визуала рубрики.\n"
        "4. Промпт для KIE должен визуально отражать именно эту рубрику "
        "(например: разбор ≠ чек-лист ≠ юмор ≠ сериал). "
        "Запрещено делать нейтральную универсальную инфографику, если рубрика задаёт другой стиль.\n"
        "5. В image/video промпте все смысловые надписи — только кириллица (русский алфавит). "
        "Каждую фразу для картинки пиши в «ёлочках» точно по-русски. "
        "Запрети латиницу в смысловом тексте "
        + (
            f"(кроме подписи внизу `{brand_site}`). "
            if brand_site
            else "(не выдумывай сайт внизу, если подпись не задана). "
        )
        + "Потребуй крупный чёткий рубленый шрифт без ошибок и без псевдокириллицы.\n"
        "6. В конце — короткий чек-лист перед публикацией.\n"
        "Если выбрано video, укажи маршрут text_to_video или image_to_video, "
        "видеомодель и при необходимости отдельно image prompt для GPT Image 2 "
        "и video prompt для анимации."
    )

    return "\n\n---\n\n".join(sections)


def build_claude_payload(user_message: str, *, rubric_lock: str = "") -> dict:
    system = (
        "Отвечай только текстом по заданному формату. "
        "Не вызывай инструменты, не запрашивай файлы и не используй tool_use. "
        "Все необходимые материалы уже включены в сообщение пользователя."
    )
    if rubric_lock:
        system += (
            f" Обязательно соблюдай рубрику «{rubric_lock}»: "
            "стиль текста и стиль визуала должны соответствовать её промпту, "
            "а не общим шаблонам."
        )
    return {
        "model": "claude-sonnet-4-6",
        "max_tokens": 3200,
        "stream": False,
        "system": system,
        "tool_choice": {"type": "none"},
        "messages": [
            {
                "role": "user",
                "content": user_message,
            }
        ],
    }


def extract_text_from_response(response_data: dict) -> str:
    content = response_data.get("content", [])
    if isinstance(content, str):
        return content

    text_parts = []
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and item.get("text"):
                text_parts.append(item["text"])
            elif item.get("type") == "tool_use":
                continue

    return "\n\n".join(text_parts).strip()


def make_anthropic_request(payload: dict, api_key: str) -> dict:
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": DEFAULT_USER_AGENT,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        ANTHROPIC_CLAUDE_URL,
        data=body,
        method="POST",
        headers=headers,
    )

    try:
        with request.urlopen(req, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"HTTP {exc.code} при вызове прямого Claude API: {error_body}"
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(f"Ошибка сети при вызове прямого Claude API: {exc}") from exc


def _friendly_text_provider_error(exc: BaseException) -> str:
    """Короткое сообщение для UI без сырого JSON."""
    text = str(exc or "")
    low = text.lower()
    if "429" in text or "rate" in low or "too many" in low:
        return (
            "Сервис текста сейчас перегружен (слишком много запросов). "
            "Подождите 1–2 минуты и нажмите «ИИ генерация» снова. "
            "Ваш промпт в поле уже сохранён — можно просто нажать «Сохранить канал»."
        )
    if "not found" in low and ("model" in low or "claude" in low):
        return (
            "Резервная текстовая модель в VseGPT указана неверно. "
            "Проверьте в .env: VSEGPT_TEXT_MODEL=anthropic/claude-sonnet-4.6"
        )
    if "vsegpt" in low and ("400" in text or "401" in text or "403" in text):
        return "Резерв VseGPT не принял запрос. Проверьте ключ VSEGPT_API_KEY и имя модели в .env."
    if "kie" in low and ("401" in text or "403" in text):
        return "KIE отклонил ключ. Проверьте KIE_API_KEY в .env."
    # Обрезаем длинный JSON
    short = text
    if len(short) > 280:
        short = short[:277] + "…"
    return short


def send_claude_request(payload: dict, api_key: str, provider: str) -> dict:
    if provider == "anthropic":
        return make_anthropic_request(payload, api_key)

    if provider == "vsegpt":
        import vsegpt_provider as vsegpt

        return vsegpt.send_claude_via_vsegpt(payload, api_key)

    try:
        return make_json_request(
            KIE_CLAUDE_URL,
            api_key,
            payload=payload,
            method="POST",
            extra_headers={
                "X-Api-Key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
            },
        )
    except Exception as kie_exc:
        import vsegpt_provider as vsegpt

        if not vsegpt.is_vsegpt_configured():
            raise RuntimeError(_friendly_text_provider_error(kie_exc)) from kie_exc
        try:
            vsegpt_key = vsegpt.get_vsegpt_api_key()
            return vsegpt.send_claude_via_vsegpt(payload, vsegpt_key)
        except Exception as vsegpt_exc:
            raise RuntimeError(
                _friendly_text_provider_error(kie_exc)
                + " "
                + _friendly_text_provider_error(vsegpt_exc)
            ) from vsegpt_exc


def split_sections(markdown_text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current_title = "_root"
    buffer: list[str] = []

    for line in markdown_text.splitlines():
        heading_match = re.match(r"^#{1,3}\s+(.+?)\s*$", line)
        if heading_match:
            sections[current_title] = "\n".join(buffer).strip()
            current_title = heading_match.group(1).strip()
            buffer = []
            continue
        buffer.append(line)

    sections[current_title] = "\n".join(buffer).strip()
    return sections


def extract_first_code_block(text: str) -> str:
    match = re.search(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Модель часто отдаёт промпт в blockquote (>) вместо ``` — тоже принимаем
    quote_lines: list[str] = []
    for line in (text or "").splitlines():
        if line.startswith(">"):
            quote_lines.append(re.sub(r"^>\s?", "", line))
        elif quote_lines:
            break
    quoted = "\n".join(quote_lines).strip()
    if len(quoted) >= 40:
        return quoted
    return ""


def get_section_by_prefix(sections: dict[str, str], prefix: str) -> str:
    for title, content in sections.items():
        if title.startswith(prefix):
            return content
    return ""


def extract_vk_post_text(answer_text: str) -> str:
    sections = split_sections(answer_text)
    post_text = get_section_by_prefix(sections, "1. Черновик поста")
    if not post_text:
        post_text = get_section_by_prefix(sections, "Черновик поста")
    if not post_text:
        return answer_text.strip()

    cleaned_lines = []
    for line in post_text.splitlines():
        if line.strip() == "---":
            continue
        cleaned_lines.append(line.rstrip())
    return "\n".join(cleaned_lines).strip()


def validate_clean_post_text(post_text: str, input_data: dict | None = None) -> dict:
    errors: list[str] = []
    input_data = input_data or {}
    source_text = json.dumps(input_data, ensure_ascii=False).lower()

    if re.search(r"[%×−÷=+]", post_text):
        errors.append(
            "В чистом тексте VK-поста найдены знак процента или математические символы. Пишите ставки и расчёт словами."
        )
    if re.search(r"\b\d+\s*/\s*\d+\b", post_text):
        errors.append(
            "В чистом тексте VK-поста найдена формульная дробь. Пишите расчёт словами."
        )
    found_unconfirmed = [
        marker
        for marker in UNCONFIRMED_TEXT_MARKERS
        if marker.lower() in post_text.lower() and marker.lower() not in source_text
    ]
    if found_unconfirmed:
        errors.append(
            "В чистом тексте VK-поста найдены маркеры, которые требуют явного источника во входных данных: "
            + ", ".join(found_unconfirmed)
        )

    return {
        "is_safe": not errors,
        "errors": errors,
    }


def extract_code_blocks(text: str) -> list[str]:
    return re.findall(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)


def extract_named_code_block(text: str, label_patterns: list[str]) -> str:
    for pattern in label_patterns:
        regex = rf"{pattern}.*?```(?:\w+)?\n(.*?)```"
        match = re.search(regex, text, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    return ""


def normalize_video_provider(raw: str | None, default: str = "kling") -> str:
    """Привести имя провайдера к одному из VIDEO_PROVIDERS."""
    key = (raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "kling": "kling",
        "kling3": "kling",
        "kling_3": "kling",
        "kling_3_0": "kling",
        "minimax": "minimax",
        "minimax_h3": "minimax",
        "minimaxh3": "minimax",
        "hailuo03": "minimax",
        "hailuo_03": "minimax",
        "veo": "veo",
        "veo3": "veo",
        "veo_3": "veo",
        "veo3_1": "veo",
        "veo_3_1": "veo",
        "hailuo": "hailuo",
        "hailuo02": "hailuo",
        "hailuo_02": "hailuo",
    }
    resolved = aliases.get(key, key)
    if resolved in VIDEO_PROVIDERS:
        return resolved
    return default if default in VIDEO_PROVIDERS else "kling"


def infer_video_model(visual_section: str, prompt_section: str) -> str:
    lowered = f"{visual_section}\n{prompt_section}".lower()
    if "minimax" in lowered or "hailuo 03" in lowered or "hailuo03" in lowered:
        return "minimax"
    if "hailuo" in lowered:
        return "hailuo"
    if "kling" in lowered:
        return "kling"
    if "veo" in lowered:
        return "veo"
    return "kling"


def infer_video_route(visual_section: str, prompt_section: str) -> str:
    lowered = f"{visual_section}\n{prompt_section}".lower()
    if "image_to_video" in lowered or "image-to-video" in lowered:
        return "image_to_video"
    if "text_to_video" in lowered or "text-to-video" in lowered:
        return "text_to_video"
    return "text_to_video"


def detect_text_in_video_prompt(prompt_text: str) -> bool:
    lowered = prompt_text.lower()
    if any(marker in lowered for marker in VIDEO_TEXT_MARKERS):
        return True

    quoted_chunks = re.findall(r'"([^"]+)"', prompt_text)
    return any(re.search(r"[А-Яа-яЁё]", chunk) for chunk in quoted_chunks)


def clean_visual_prompt(prompt_text: str) -> tuple[str, str, str, str]:
    aspect_ratio = "1:1"
    resolution = "1K"
    output_format = "png"

    aspect_match = re.search(r"Aspect ratio:\s*([0-9:]+|auto)", prompt_text, re.IGNORECASE)
    resolution_match = re.search(r"Resolution:\s*(1K|2K|4K)", prompt_text, re.IGNORECASE)
    format_match = re.search(r"Output format:\s*(png|jpg)", prompt_text, re.IGNORECASE)

    if aspect_match:
        aspect_ratio = aspect_match.group(1)
    if resolution_match:
        resolution = resolution_match.group(1).upper()
    if format_match:
        output_format = format_match.group(1).lower()

    cleaned_prompt = re.sub(r"Aspect ratio:\s*([0-9:]+|auto)\.?", "", prompt_text, flags=re.IGNORECASE)
    cleaned_prompt = re.sub(r"Resolution:\s*(1K|2K|4K)\.?", "", cleaned_prompt, flags=re.IGNORECASE)
    cleaned_prompt = re.sub(r"Output format:\s*(png|jpg)\.?", "", cleaned_prompt, flags=re.IGNORECASE)
    cleaned_prompt = re.sub(r"\n{3,}", "\n\n", cleaned_prompt).strip(" \n.")
    return cleaned_prompt.strip(), aspect_ratio, resolution, output_format


def infer_duration_seconds(prompt_text: str, default: int = 5) -> int:
    match = re.search(r"(\d{1,2})(?:\s*[–-]\s*(\d{1,2}))?\s*seconds", prompt_text, re.IGNORECASE)
    if not match:
        return default

    first_value = int(match.group(1))
    second_value = match.group(2)
    if second_value:
        return max(3, min(15, int(second_value)))
    return max(3, min(15, first_value))


def extract_visual_data(answer_text: str) -> dict:
    sections = split_sections(answer_text)
    visual_section = sections.get("3. Рекомендация по визуалу", "")
    prompt_section = sections.get(f"4. Промпт для KIE ({KIE_IMAGE_MODEL_LABEL})", "")
    if not prompt_section:
        prompt_section = sections.get("4. Промпт для KIE (Nano Banana Pro)", "")
    if not prompt_section:
        prompt_section = sections.get("4. Промпт для KIE", "")
    if not prompt_section:
        prompt_section = get_section_by_prefix(sections, "4. Промпт для KIE")

    visual_type = "unknown"
    lowered = visual_section.lower()
    # video раньше image, чтобы «image-to-video» не ломал выбор
    if (
        "`video`" in lowered
        or "формат: `video`" in lowered
        or "формат: video" in lowered
        or "выбор: `video`" in lowered
        or "выбор: video" in lowered
        or "видео" in lowered
        or "ролик" in lowered
        or "клип" in lowered
        or "kling" in lowered
    ):
        visual_type = "video"
    elif (
        "`image`" in lowered
        or "image" in lowered
        or "формат: `image`" in lowered
        or "формат: image" in lowered
        or "выбор: `image`" in lowered
        or "выбор: image" in lowered
        or "изображен" in lowered
        or "картинк" in lowered
        or "инфографик" in lowered
        or "статичн" in lowered
        or "обложк" in lowered
    ):
        visual_type = "image"

    prompt_text = extract_first_code_block(prompt_section)
    # Если кодовых блоков нет — берём самый длинный абзац из раздела 4
    if not prompt_text and prompt_section:
        paragraphs = [
            p.strip()
            for p in re.split(r"\n\s*\n", prompt_section)
            if len(p.strip()) >= 60 and not p.strip().startswith("**")
        ]
        if paragraphs:
            prompt_text = max(paragraphs, key=len)
    image_prompt_text = ""
    video_prompt_text = ""
    video_model = infer_video_model(visual_section, prompt_section)
    video_route = infer_video_route(visual_section, prompt_section)

    if visual_type == "video":
        image_prompt_text = extract_named_code_block(
            prompt_section,
            [
                r"image prompt\s*\(gpt image 2\)",
                r"image prompt\s*\(nano banana pro\)",
                r"image prompt",
                r"gpt image 2",
                r"nano banana pro",
                r"кадр для gpt image",
                r"кадр для nano banana",
            ],
        )
        video_prompt_text = extract_named_code_block(
            prompt_section,
            [
                r"video prompt",
                r"промпт для video",
                r"промпт для hailuo",
                r"промпт для kling",
                r"промпт для veo",
            ],
        )

        all_blocks = [block.strip() for block in extract_code_blocks(prompt_section) if block.strip()]
        if not video_prompt_text and all_blocks:
            if image_prompt_text and len(all_blocks) >= 2:
                video_prompt_text = all_blocks[-1]
            else:
                video_prompt_text = all_blocks[0]
        if not image_prompt_text and video_route == "image_to_video" and len(all_blocks) >= 2:
            image_prompt_text = all_blocks[0]

        if not video_prompt_text:
            video_prompt_text = prompt_text
        if video_route == "text_to_video" and detect_text_in_video_prompt(video_prompt_text):
            video_route = "image_to_video"

        if not image_prompt_text and video_route == "image_to_video":
            image_prompt_text = video_prompt_text

    cleaned_prompt, aspect_ratio, resolution, output_format = clean_visual_prompt(prompt_text)
    cleaned_image_prompt, image_aspect_ratio, image_resolution, image_output_format = clean_visual_prompt(
        image_prompt_text or prompt_text
    )
    cleaned_video_prompt, _, _, _ = clean_visual_prompt(video_prompt_text or prompt_text)

    # Если тип не распознали, но промпт есть — считаем картинкой
    if visual_type == "unknown" and (cleaned_prompt or cleaned_image_prompt):
        visual_type = "image"

    return {
        "visual_type": visual_type,
        "prompt_text": cleaned_prompt.strip(),
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "output_format": output_format,
        "video_model": video_model,
        "video_route": video_route,
        "image_prompt_text": cleaned_image_prompt.strip(),
        "image_prompt_aspect_ratio": image_aspect_ratio or "9:16",
        "image_prompt_resolution": image_resolution or "1K",
        "image_prompt_output_format": image_output_format or "png",
        "video_prompt_text": cleaned_video_prompt.strip(),
        "video_has_text_overlay": detect_text_in_video_prompt(video_prompt_text or prompt_text),
    }


def validate_visual_prompt(visual_data: dict, *, brand_footer: str = "") -> dict:
    prompt_text = visual_data.get("prompt_text", "")
    lowered = prompt_text.lower()
    brand = (brand_footer or "").strip()
    prompt_without_brand = prompt_text
    if brand:
        prompt_without_brand = re.sub(re.escape(brand), "", prompt_text, flags=re.IGNORECASE)
    # HEX-цвета (#1E2A6E) в стилевых промптах — не считаем URL/доменом
    prompt_for_meta_checks = re.sub(
        r"#[0-9A-Fa-f]{3,8}\b",
        "",
        prompt_without_brand,
    )
    errors: list[str] = []
    warnings: list[str] = []

    for phrase in VISUAL_FORBIDDEN_PHRASES:
        if phrase in lowered:
            errors.append(f"Найдена рискованная фраза для картинки: `{phrase}`")

    quoted_chunks = re.findall(r'"([^"]+)"', prompt_text)
    long_russian_chunks = [
        chunk for chunk in quoted_chunks
        if re.search(r"[А-Яа-яЁё]", chunk) and len(chunk) > 35
    ]
    if long_russian_chunks:
        warnings.append(
            "В промпте есть длинные русские фразы для изображения. "
            "Лучше оставлять на картинке только короткие подписи."
        )

    if len(quoted_chunks) >= 4:
        warnings.append(
            "В промпте много текстовых вставок в кавычках. "
            "Изображение может получиться перегруженным."
        )

    # Подпись внизу — только если пользователь её задал
    if brand and brand.lower() not in lowered:
        warnings.append(
            f"В image-промпте нет заданной подписи `{brand}`. Лучше добавить её маленьким текстом внизу."
        )

    # Латиница опасна только в тексте НА картинке (в «ёлочках» / кавычках)
    overlay_chunks = re.findall(r"«([^»]+)»", prompt_text) + re.findall(r'"([^"]+)"', prompt_text)
    latin_overlays = []
    for chunk in overlay_chunks:
        leftovers = _overlay_text_without_allowed_latin(chunk, brand)
        if re.search(r"[A-Za-z]", leftovers):
            latin_overlays.append(chunk)
    if latin_overlays:
        errors.append(
            "В тексте на картинке (в кавычках) найдена латиница. "
            "Надписи в кадре — только кириллицей. Проблемные фразы: "
            + "; ".join(f"«{c[:40]}»" for c in latin_overlays[:3])
        )
    if re.search(r"https?://|www\.|[A-Za-z0-9.-]+\.[A-Za-z]{2,}", prompt_for_meta_checks):
        errors.append("В image-промпте найден сторонний URL или адрес сайта.")
    if re.search(r"[$€£₽]", prompt_for_meta_checks):
        errors.append("В image-промпте найдены валютные знаки. Для картинки пишите суммы словами.")
    if re.search(r"[%×−÷=+]", prompt_for_meta_checks):
        errors.append(
            "В image-промпте найдены знак процента или математические символы. Для картинки пишите ставки и расчёт словами."
        )
    if re.search(r"\b\d+\s*/\s*\d+\b", prompt_for_meta_checks):
        errors.append(
            "В image-промпте найдена формульная запись с дробью. Для картинки пишите расчёт словами."
        )
    if re.search(r"[→←↔]", prompt_for_meta_checks):
        errors.append("В image-промпте найдены символы стрелок в тексте. Стрелки допустимы только как графические линии.")

    is_safe = not errors
    return {
        "is_safe": is_safe,
        "errors": errors,
        "warnings": warnings,
        "safe_suggestions": VISUAL_SAFE_SUGGESTIONS,
    }


CYRILLIC_IMAGE_LOCK = (
    " CRITICAL TYPOGRAPHY / ОБЯЗАТЕЛЬНАЯ КИРИЛЛИЦА: "
    "Весь смысловой текст на изображении — только русский алфавит (кириллица). "
    "Каждую русскую фразу в кавычках «...» отрисовать ТОЧНО как написано, крупно, чётко, "
    "контрастно, без орфографических ошибок и без «ломаной» кириллицы. "
    "Запрещено: латиница в смысловых надписях, смесь латиницы и кириллицы в одном слове, "
    "псевдокириллица, нечитаемый текст, иероглифы, англоязычные слова вместо русских. "
    "Подпись внизу добавляй только если она явно задана в промпте. "
    "Шрифт: простой рубленый sans-serif, высокая читаемость, ровные буквы."
)

CYRILLIC_VIDEO_LOCK = (
    " CRITICAL TYPOGRAPHY / ОБЯЗАТЕЛЬНАЯ КИРИЛЛИЦА В КАДРЕ: "
    "Если в кадре есть текст — только русский алфавит (кириллица), чёткий и читаемый. "
    "Не искажать русские буквы, не заменять их латиницей, не допускать размытых каракуль. "
    "Текст в кадре должен оставаться стабильным и разборчивым на всём протяжении ролика. "
    "Подпись внизу — только если она явно задана в промпте."
)


def enforce_cyrillic_visual_prompt(prompt_text: str, *, kind: str = "image") -> str:
    """Добавляет жёсткое требование кириллицы к промпту картинки/видео."""
    text = (prompt_text or "").strip()
    if not text:
        return text
    lock = CYRILLIC_IMAGE_LOCK if kind == "image" else CYRILLIC_VIDEO_LOCK
    # не дублировать, если уже добавили
    if "ОБЯЗАТЕЛЬНАЯ КИРИЛЛИЦА" in text:
        return text
    return f"{text}\n\n{lock}"


def filter_public_reference_urls(urls: list[str] | None) -> list[str]:
    """Только URL, которые внешний API реально может скачать (не localhost)."""
    out: list[str] = []
    for raw in urls or []:
        u = str(raw or "").strip()
        if not u.startswith("http"):
            continue
        lower = u.lower()
        if "127.0.0.1" in lower or "localhost" in lower:
            continue
        out.append(u)
    return out[:8]


def is_externally_accessible_url(url: str) -> bool:
    u = (url or "").strip()
    if not u.startswith("http"):
        return False
    lower = u.lower()
    return "127.0.0.1" not in lower and "localhost" not in lower


def detect_real_person_required(
    prompt_text: str = "",
    *,
    reference_names: list[str] | None = None,
    local_files: list[dict] | None = None,
) -> tuple[bool, str]:
    """
    Нужен ли реальный персонаж в кадре (reference_required).
    Возвращает (required, person_label).
    """
    blobs: list[str] = [prompt_text or ""]
    for name in reference_names or []:
        blobs.append(str(name or ""))
    for item in local_files or []:
        if not isinstance(item, dict):
            continue
        blobs.append(str(item.get("name") or ""))
        blobs.append(str(item.get("path") or ""))
    hay = "\n".join(blobs)
    if not _REAL_PERSON_HINT_RE.search(hay):
        # Есть локальные фото-референсы канала — считаем, что персонаж может быть нужен,
        # если в промпте уже есть правило реальных фото.
        if local_files and (
            "Правило реальных фото" in (prompt_text or "")
            or "максимально сохрани" in (prompt_text or "").lower()
        ):
            return True, "person"
        return False, "none"

    low = hay.lower()
    if re.search(r"ксени|kseni", low):
        return True, "Ksenia"
    if re.search(r"бульдог|bulldog", low):
        return True, "Bulldog"
    if re.search(r"собак|п[её]с\b", low):
        return True, "dog"
    if re.search(r"кот\b|кошк", low):
        return True, "cat"
    return True, "person"


def upload_local_file_to_kie_temp(
    api_key: str,
    *,
    file_path: Path | None = None,
    data_b64: str = "",
    media_type: str = "image/jpeg",
    file_name: str = "reference.jpg",
) -> str:
    """
    Нативный KIE File Upload API: base64 → временный публичный downloadUrl.
    Vision-base64 ≠ generation reference, пока файл не залит сюда.
    """
    payload_b64 = (data_b64 or "").strip()
    if not payload_b64:
        if not file_path or not Path(file_path).is_file():
            raise RuntimeError("Нет данных файла для upload в KIE.")
        raw = Path(file_path).read_bytes()
        if not raw:
            raise RuntimeError("Пустой файл референса.")
        import base64 as _b64

        payload_b64 = _b64.standard_b64encode(raw).decode("ascii")
        if not media_type or media_type == "application/octet-stream":
            # лёгкая эвристика по расширению
            suf = Path(file_path).suffix.lower()
            media_type = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
                ".gif": "image/gif",
            }.get(suf, "image/jpeg")

    data_url = payload_b64
    if not data_url.startswith("data:"):
        data_url = f"data:{media_type or 'image/jpeg'};base64,{payload_b64}"

    safe_name = re.sub(r"[^\w.\-]+", "_", (file_name or "reference.jpg"))[:80] or "reference.jpg"
    if "." not in safe_name:
        safe_name += ".jpg"

    body = {
        "base64Data": data_url,
        "uploadPath": "smm-channel-refs",
        "fileName": safe_name,
    }
    resp = make_json_request(
        KIE_FILE_BASE64_UPLOAD_URL,
        api_key,
        payload=body,
        method="POST",
    )
    data = resp.get("data") if isinstance(resp, dict) else None
    if not isinstance(data, dict):
        raise RuntimeError(f"KIE file upload: неожиданный ответ: {resp}")
    download_url = (data.get("downloadUrl") or data.get("download_url") or "").strip()
    if not download_url.startswith("http"):
        raise RuntimeError(f"KIE file upload: нет downloadUrl: {resp}")
    if not is_externally_accessible_url(download_url):
        raise RuntimeError(f"KIE file upload вернул недоступный URL: {download_url}")
    return download_url


def prepare_generation_reference_urls(
    api_key: str,
    *,
    public_urls: list[str] | None = None,
    local_files: list[dict] | None = None,
    max_refs: int = 8,
) -> dict:
    """
    Собирает URL, которые image API реально сможет скачать.
    Локальные файлы → KIE tempfile upload (base64 API).
    vision_reference (просто наличие файла) ≠ generation_reference.
    """
    sent: list[str] = []
    types: list[str] = []
    errors: list[str] = []

    for u in filter_public_reference_urls(public_urls):
        if len(sent) >= max_refs:
            break
        sent.append(u)
        types.append("url")

    for item in local_files or []:
        if len(sent) >= max_refs:
            break
        if not isinstance(item, dict):
            continue
        path_raw = (item.get("path") or "").strip()
        name = (item.get("name") or Path(path_raw).name or "reference.jpg").strip()
        media_type = (item.get("media_type") or "image/jpeg").strip()
        data_b64 = (item.get("data_b64") or "").strip()
        try:
            url = upload_local_file_to_kie_temp(
                api_key,
                file_path=Path(path_raw) if path_raw else None,
                data_b64=data_b64,
                media_type=media_type,
                file_name=name,
            )
            sent.append(url)
            types.append("base64_upload")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")

    gen_type = "none"
    if types:
        if all(t == "url" for t in types):
            gen_type = "url"
        elif all(t == "base64_upload" for t in types):
            gen_type = "base64"
        else:
            gen_type = "mixed"

    return {
        "urls": sent,
        "count": len(sent),
        "generation_reference_type": gen_type,
        "externally_accessible": bool(sent) and all(is_externally_accessible_url(u) for u in sent),
        "upload_errors": errors,
        "vision_local_count": len(local_files or []),
        "public_url_candidates": len(filter_public_reference_urls(public_urls)),
    }


def log_generation_reference_audit(
    *,
    reference_required: bool,
    person_label: str,
    vision_count: int,
    prepared: dict,
) -> None:
    """Обязательный лог перед image generation API call."""
    urls = prepared.get("urls") or []
    lines = [
        "=== GENERATION REFERENCE AUDIT ===",
        f"REAL PERSON REQUIRED: {'yes' if reference_required else 'no'}",
        f"PERSON: {person_label or 'none'}",
        f"VISION REFERENCES: {vision_count}",
        f"GENERATION REFERENCES: {prepared.get('count', 0)}",
        f"GENERATION REFERENCE TYPE: {prepared.get('generation_reference_type', 'none')}",
        f"EXTERNALLY ACCESSIBLE: {'yes' if prepared.get('externally_accessible') else 'no'}",
        "IMAGE_INPUT SENT:",
    ]
    if urls:
        for u in urls:
            lines.append(f"  - {u}")
    else:
        lines.append("  - (none)")
    errs = prepared.get("upload_errors") or []
    if errs:
        lines.append("UPLOAD ERRORS:")
        for e in errs[:5]:
            lines.append(f"  - {e}")
    lines.append("=== END AUDIT ===")
    print("\n".join(lines), flush=True)


def strip_real_person_for_failsafe(prompt_text: str) -> str:
    """Запрет генерации конкретного человека без реального reference."""
    text = (prompt_text or "").strip()
    if REAL_PERSON_REFERENCE_UNAVAILABLE in text:
        return text
    return (text + _NO_PERSON_FALLBACK_LOCK).strip()


def build_image_payload(
    visual_data: dict,
    *,
    reference_image_urls: list[str] | None = None,
) -> dict:
    prompt = enforce_cyrillic_visual_prompt(visual_data["prompt_text"], kind="image")
    ref_urls = filter_public_reference_urls(reference_image_urls)
    aspect = visual_data.get("aspect_ratio") or "4:5"
    resolution = visual_data.get("resolution") or "1K"

    if ref_urls:
        # Реальные фото → нативная image-to-image модель KIE (input_urls)
        input_payload = {
            "prompt": prompt,
            "input_urls": ref_urls,
            "aspect_ratio": aspect if aspect != "auto" else "auto",
        }
        if resolution in ("1K", "2K", "4K"):
            input_payload["resolution"] = resolution
        return {
            "model": KIE_IMAGE_TO_IMAGE_MODEL,
            "input": input_payload,
        }

    input_payload = {
        "prompt": prompt,
        "aspect_ratio": aspect,
        "resolution": resolution,
    }
    return {
        "model": KIE_IMAGE_MODEL,
        "input": input_payload,
    }


def build_base_image_payload(
    visual_data: dict,
    *,
    reference_image_urls: list[str] | None = None,
) -> dict:
    prompt = enforce_cyrillic_visual_prompt(
        visual_data["image_prompt_text"], kind="image"
    )
    ref_urls = filter_public_reference_urls(reference_image_urls)
    aspect = visual_data.get("image_prompt_aspect_ratio", "9:16")
    resolution = visual_data.get("image_prompt_resolution", "1K")
    if ref_urls:
        input_payload = {
            "prompt": prompt,
            "input_urls": ref_urls,
            "aspect_ratio": aspect if aspect != "auto" else "auto",
        }
        if resolution in ("1K", "2K", "4K"):
            input_payload["resolution"] = resolution
        return {
            "model": KIE_IMAGE_TO_IMAGE_MODEL,
            "input": input_payload,
        }
    input_payload = {
        "prompt": prompt,
        "aspect_ratio": aspect,
        "resolution": resolution,
    }
    return {
        "model": KIE_IMAGE_MODEL,
        "input": input_payload,
    }


def build_veo_video_payload(visual_data: dict, base_image_url: str | None = None) -> dict:
    payload = {
        "prompt": visual_data["video_prompt_text"],
        "model": "veo3_fast",
        "aspect_ratio": "9:16",
        "enableTranslation": True,
    }
    if base_image_url:
        payload["imageUrls"] = [base_image_url]
        payload["generationType"] = "FIRST_AND_LAST_FRAMES_2_VIDEO"
    else:
        payload["generationType"] = "TEXT_2_VIDEO"
    return payload


def build_hailuo_video_payload(visual_data: dict, base_image_url: str | None = None) -> dict:
    if base_image_url:
        return {
            "model": HAILUO_IMAGE_MODEL,
            "input": {
                "prompt": visual_data["video_prompt_text"],
                "image_url": base_image_url,
                "prompt_optimizer": True,
                "nsfw_checker": False,
            },
        }

    return {
        "model": HAILUO_TEXT_MODEL,
        "input": {
            "prompt": visual_data["video_prompt_text"],
            "prompt_optimizer": True,
            "nsfw_checker": False,
        },
    }


def _minimax_duration(visual_data: dict, default: int = 6) -> int:
    raw_prompt = (visual_data.get("video_prompt_text") or "").strip()
    duration = infer_duration_seconds(raw_prompt, default=default)
    return max(4, min(15, int(duration)))


def _minimax_aspect_ratio(visual_data: dict) -> str:
    allowed = {"21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}
    ratio = (
        (visual_data.get("aspect_ratio") or "").strip()
        or (visual_data.get("image_prompt_aspect_ratio") or "").strip()
        or "9:16"
    )
    return ratio if ratio in allowed else "9:16"


def build_minimax_video_payload(
    visual_data: dict, base_image_url: str | None = None
) -> dict:
    """MiniMax H3 (Hailuo 03) через KIE Market createTask."""
    raw_prompt = enforce_cyrillic_visual_prompt(
        (visual_data.get("video_prompt_text") or "").strip(), kind="video"
    )
    if len(raw_prompt) > 7000:
        raw_prompt = raw_prompt[:7000].rstrip() + "…"
    duration = _minimax_duration(visual_data, default=6)
    resolution = "768P"  # быстрее и дешевле для SMM; 2K при необходимости позже

    if base_image_url:
        return {
            "model": MINIMAX_IMAGE_MODEL,
            "input": {
                "prompt": raw_prompt,
                "first_frame_url": base_image_url,
                "duration": duration,
                "resolution": resolution,
            },
        }

    return {
        "model": MINIMAX_TEXT_MODEL,
        "input": {
            "prompt": raw_prompt,
            "aspect_ratio": _minimax_aspect_ratio(visual_data),
            "duration": duration,
            "resolution": resolution,
        },
    }


def build_kling_video_payload(
    visual_data: dict,
    base_image_url: str | None = None,
    *,
    mode: str = "pro",
) -> dict:
    raw_prompt = (visual_data.get("video_prompt_text") or "").strip()
    raw_prompt = enforce_cyrillic_visual_prompt(raw_prompt, kind="video")
    # Слишком длинный промпт часто ломает Kling — оставляем суть + lock
    if len(raw_prompt) > 1400:
        # сохраняем хвост с требованием кириллицы
        lock_marker = "ОБЯЗАТЕЛЬНАЯ КИРИЛЛИЦА"
        if lock_marker in raw_prompt:
            main, lock = raw_prompt.split(lock_marker, 1)
            main = main[:1100].rstrip() + "…"
            raw_prompt = f"{main}\n\n{lock_marker}{lock}"
        else:
            raw_prompt = raw_prompt[:1400].rstrip() + "…"

    duration = infer_duration_seconds(raw_prompt, default=5)
    duration = max(3, min(15, int(duration)))

    input_payload = {
        "prompt": raw_prompt,
        "sound": False,
        "duration": str(duration),
        "mode": mode if mode in {"std", "pro", "4K"} else "pro",
        "multi_shots": False,
        "multi_prompt": [],
    }
    if base_image_url:
        # При кадре aspect_ratio опционален — система подстроит сама
        input_payload["image_urls"] = [base_image_url]
    else:
        input_payload["aspect_ratio"] = "9:16"

    return {
        "model": KLING_VIDEO_MODEL,
        "input": input_payload,
    }


def build_video_payload(
    visual_data: dict,
    video_provider: str,
    base_image_url: str | None = None,
    *,
    kling_mode: str = "pro",
) -> dict:
    provider = video_provider
    if provider == "auto":
        provider = visual_data.get("video_model", "kling")
    provider = normalize_video_provider(provider, default="kling")

    if provider == "veo":
        return build_veo_video_payload(visual_data, base_image_url)
    if provider == "hailuo":
        return build_hailuo_video_payload(visual_data, base_image_url)
    if provider == "minimax":
        return build_minimax_video_payload(visual_data, base_image_url)
    if provider == "kling":
        return build_kling_video_payload(
            visual_data, base_image_url, mode=kling_mode
        )

    raise ValueError(f"Неизвестный video provider: {video_provider}")


def create_image_task(payload: dict, api_key: str) -> dict:
    return make_json_request(KIE_IMAGE_TASK_URL, api_key, payload=payload, method="POST")


def create_video_task(payload: dict, api_key: str) -> dict:
    model = (payload.get("model") or "").strip()
    if model in MARKET_VIDEO_MODELS or model.startswith("minimax-h3/"):
        return make_json_request(KIE_IMAGE_TASK_URL, api_key, payload=payload, method="POST")
    return make_json_request(KIE_VEO_GENERATE_URL, api_key, payload=payload, method="POST")


def get_task_info(task_id: str, api_key: str) -> dict:
    url = KIE_TASK_INFO_URL.format(task_id=task_id)
    return make_json_request(url, api_key, payload=None, method="GET")


def get_veo_task_info(task_id: str, api_key: str) -> dict:
    url = KIE_VEO_INFO_URL.format(task_id=task_id)
    return make_json_request(url, api_key, payload=None, method="GET")


def wait_for_task_result(task_id: str, api_key: str, timeout_sec: int = 900) -> dict:
    deadline = time.time() + timeout_sec
    sleep_sec = 3

    while time.time() < deadline:
        data = get_task_info(task_id, api_key)
        task_data = data.get("data", {})
        state = task_data.get("state")

        if state == "success":
            return data
        if state == "fail":
            fail_msg = task_data.get("failMsg", "Неизвестная ошибка генерации.")
            raise RuntimeError(f"Генерация изображения завершилась ошибкой: {fail_msg}")

        time.sleep(sleep_sec)
        sleep_sec = min(sleep_sec + 2, 10)

    raise RuntimeError("Таймаут ожидания результата генерации изображения.")


def generate_image_url_with_fallback(
    image_vd: dict,
    *,
    reference_image_urls: list[str] | None = None,
    reference_local_files: list[dict] | None = None,
    reference_image_names: list[str] | None = None,
    kie_key: str | None = None,
    allow_no_person_fallback: bool = True,
) -> tuple[str, str]:
    """
    Картинка с проверкой generation references ПЕРЕД API call.

    vision_reference != generation_reference:
    локальные файлы заливаются в KIE tempfile (base64 upload), затем
    gpt-image-2-image-to-image с input_urls.

    VseGPT не принимает image refs — при наличии generation refs идём
    сразу в KIE. Если нужен реальный персонаж, а refs нет — fail-safe
    (сцена без человека) или ошибка REAL_PERSON_REFERENCE_UNAVAILABLE.
    """
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    import vsegpt_provider as vsegpt

    key = kie_key or get_api_key()
    prompt_text = image_vd.get("prompt_text", "") or ""
    local_files = list(reference_local_files or [])
    names = list(reference_image_names or [])
    for item in local_files:
        if isinstance(item, dict) and (item.get("name") or "").strip():
            names.append(str(item["name"]).strip())

    reference_required, person_label = detect_real_person_required(
        prompt_text,
        reference_names=names,
        local_files=local_files,
    )
    # Если есть локальные фото канала — пытаемся всегда сделать их generation refs
    prepared = prepare_generation_reference_urls(
        key,
        public_urls=reference_image_urls,
        local_files=local_files,
        max_refs=8,
    )
    log_generation_reference_audit(
        reference_required=reference_required or bool(local_files),
        person_label=person_label if (reference_required or local_files) else "none",
        vision_count=len(local_files),
        prepared=prepared,
    )

    gen_urls = list(prepared.get("urls") or [])
    available = bool(gen_urls) and bool(prepared.get("externally_accessible"))

    if reference_required and not available:
        # Запрет: текстовое описание внешности ≠ reference
        msg = (
            f"{REAL_PERSON_REFERENCE_UNAVAILABLE}: нужен реальный фото-референс "
            f"({person_label}), но image API не получила доступный generation reference. "
            "vision_reference ≠ generation_reference; localhost URL не считаются."
        )
        if not allow_no_person_fallback:
            raise RealPersonReferenceUnavailableError(msg, person_label=person_label)
        print(
            f"FAIL-SAFE: {msg} → генерация сцены БЕЗ конкретного человека/животного.",
            flush=True,
        )
        image_vd = dict(image_vd)
        image_vd["prompt_text"] = strip_real_person_for_failsafe(prompt_text)
        gen_urls = []
        # помечаем в промпте — дальше text-to-image без input_urls

    # Есть реальные refs → только KIE image-to-image (VseGPT refs не умеет)
    if gen_urls:
        try:
            image_payload = build_image_payload(image_vd, reference_image_urls=gen_urls)
            # Финальная проверка непосредственно перед API call
            sent = (image_payload.get("input") or {}).get("input_urls") or []
            if not sent:
                raise RealPersonReferenceUnavailableError(
                    f"{REAL_PERSON_REFERENCE_UNAVAILABLE}: payload без input_urls.",
                    person_label=person_label,
                )
            print(
                "IMAGE_INPUT SENT (pre-API): "
                + ", ".join(str(u) for u in sent),
                flush=True,
            )
            task_create = create_image_task(image_payload, key)
            task_id = task_create.get("data", {}).get("taskId", "")
            if not task_id:
                raise RuntimeError("KIE не вернул taskId для image-to-image.")
            task_result = wait_for_task_result(task_id, key)
            write_image_outputs(image_vd, image_payload, task_create, task_result)
            urls = extract_result_urls(task_result)
            if urls:
                return urls[0], KIE_IMAGE_TO_IMAGE_LABEL
            raise RuntimeError("KIE image-to-image: задача без ссылки на картинку.")
        except RealPersonReferenceUnavailableError:
            raise
        except Exception as kie_i2i_exc:
            raise RuntimeError(
                f"KIE image-to-image (refs): {kie_i2i_exc}"
            ) from kie_i2i_exc

    # Без generation refs — обычный путь: VseGPT → KIE text-to-image
    vsegpt_error = ""
    timeout_sec = int(vsegpt.get_vsegpt_image_timeout_sec())

    if vsegpt.is_vsegpt_configured():
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    vsegpt.generate_image_via_vsegpt,
                    image_vd.get("prompt_text", ""),
                    aspect_ratio=image_vd.get("aspect_ratio", "4:5"),
                    timeout_sec=timeout_sec,
                )
                url = future.result(timeout=timeout_sec)
            if url:
                return url, f"VseGPT ({vsegpt.get_vsegpt_image_model()})"
            vsegpt_error = "VseGPT: пустой ответ без URL."
        except FuturesTimeout:
            vsegpt_error = f"VseGPT не ответил за {timeout_sec // 60} мин."
        except Exception as exc:  # noqa: BLE001
            vsegpt_error = str(exc)
    else:
        vsegpt_error = "VseGPT не настроен (нет VSEGPT_API_KEY)."

    try:
        image_payload = build_image_payload(image_vd, reference_image_urls=None)
        print("IMAGE_INPUT SENT (pre-API): (none — text-to-image)", flush=True)
        task_create = create_image_task(image_payload, key)
        task_id = task_create.get("data", {}).get("taskId", "")
        if not task_id:
            raise RuntimeError("KIE не вернул taskId для картинки.")
        task_result = wait_for_task_result(task_id, key)
        write_image_outputs(image_vd, image_payload, task_create, task_result)
        urls = extract_result_urls(task_result)
        if urls:
            return urls[0], f"{KIE_IMAGE_MODEL_LABEL} (резерв)"
        raise RuntimeError("KIE: задача завершилась без ссылки на картинку.")
    except Exception as kie_exc:
        raise RuntimeError(
            f"VseGPT: {vsegpt_error}. KIE (резерв): {kie_exc}"
        ) from kie_exc


def wait_for_video_result(task_id: str, api_key: str, timeout_sec: int = 480) -> dict:
    deadline = time.time() + timeout_sec
    sleep_sec = 10

    while time.time() < deadline:
        data = get_veo_task_info(task_id, api_key)
        task_data = data.get("data", {})
        success_flag = task_data.get("successFlag")

        if success_flag == 1:
            return data
        if success_flag in (2, 3):
            raise RuntimeError(
                f"Генерация видео завершилась ошибкой: {data.get('msg', 'Неизвестная ошибка.')}"
            )

        time.sleep(sleep_sec)
        sleep_sec = min(sleep_sec + 5, 20)

    raise RuntimeError("Таймаут ожидания результата генерации видео.")


def wait_for_market_video_result(task_id: str, api_key: str, timeout_sec: int = 900) -> dict:
    deadline = time.time() + timeout_sec
    sleep_sec = 6

    while time.time() < deadline:
        data = get_task_info(task_id, api_key)
        task_data = data.get("data", {})
        state = task_data.get("state")

        if state == "success":
            return data
        if state == "fail":
            fail_msg = task_data.get("failMsg", "Неизвестная ошибка генерации.")
            raise RuntimeError(f"Генерация видео завершилась ошибкой: {fail_msg}")

        time.sleep(sleep_sec)
        sleep_sec = min(sleep_sec + 4, 15)

    raise RuntimeError("Таймаут ожидания результата генерации видео.")


def wait_for_any_video_result(
    task_id: str,
    api_key: str,
    video_provider: str,
    timeout_sec: int = 900,
) -> dict:
    if video_provider == "veo":
        return wait_for_video_result(task_id, api_key, timeout_sec=timeout_sec)
    return wait_for_market_video_result(task_id, api_key, timeout_sec=timeout_sec)


def write_outputs(user_message: str, payload: dict) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(exist_ok=True)

    user_message_path = OUTPUT_DIR / "final-user-message.txt"
    payload_path = OUTPUT_DIR / "claude-request.json"

    user_message_path.write_text(user_message, encoding="utf-8")
    payload_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return user_message_path, payload_path


def write_response_outputs(response_data: dict) -> tuple[Path, Path]:
    OUTPUT_DIR.mkdir(exist_ok=True)

    response_json_path = OUTPUT_DIR / "claude-response.json"
    response_text_path = OUTPUT_DIR / "claude-answer.txt"

    response_json_path.write_text(
        json.dumps(response_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    response_text_path.write_text(
        extract_text_from_response(response_data) or "[Ответ без текстового блока]",
        encoding="utf-8",
    )

    return response_json_path, response_text_path


def write_clean_post_output(post_text: str) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    clean_post_path = OUTPUT_DIR / "vk-post-clean.txt"
    clean_post_path.write_text(post_text, encoding="utf-8")
    return clean_post_path


def write_clean_post_validation_report(post_text: str, validation_report: dict) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    validation_path = OUTPUT_DIR / "vk-post-clean-validation.json"
    validation_path.write_text(
        json.dumps(
            {
                "post_text": post_text,
                "validation": validation_report,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return validation_path


def write_image_outputs(
    visual_data: dict,
    image_payload: dict,
    task_create_response: dict,
    task_result_response: dict | None,
) -> tuple[Path, Path, Path, Path | None]:
    OUTPUT_DIR.mkdir(exist_ok=True)

    visual_data_path = OUTPUT_DIR / "image-visual-data.json"
    image_payload_path = OUTPUT_DIR / "image-request.json"
    image_task_path = OUTPUT_DIR / "image-task-create.json"
    image_result_path = OUTPUT_DIR / "image-task-result.json"

    visual_data_path.write_text(
        json.dumps(visual_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    image_payload_path.write_text(
        json.dumps(image_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    image_task_path.write_text(
        json.dumps(task_create_response, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if task_result_response is not None:
        image_result_path.write_text(
            json.dumps(task_result_response, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return visual_data_path, image_payload_path, image_task_path, image_result_path

    return visual_data_path, image_payload_path, image_task_path, None


def write_visual_validation_report(
    visual_data: dict,
    validation_report: dict,
    filename: str = "image-validation.json",
) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    report_path = OUTPUT_DIR / filename
    report_path.write_text(
        json.dumps(
            {
                "visual_data": visual_data,
                "validation": validation_report,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return report_path


def write_video_outputs(
    visual_data: dict,
    video_payload: dict,
    task_create_response: dict,
    task_result_response: dict | None,
) -> tuple[Path, Path, Path, Path | None]:
    OUTPUT_DIR.mkdir(exist_ok=True)

    visual_data_path = OUTPUT_DIR / "video-visual-data.json"
    video_payload_path = OUTPUT_DIR / "video-request.json"
    video_task_path = OUTPUT_DIR / "video-task-create.json"
    video_result_path = OUTPUT_DIR / "video-task-result.json"

    visual_data_path.write_text(
        json.dumps(visual_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    video_payload_path.write_text(
        json.dumps(video_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    video_task_path.write_text(
        json.dumps(task_create_response, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if task_result_response is not None:
        video_result_path.write_text(
            json.dumps(task_result_response, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return visual_data_path, video_payload_path, video_task_path, video_result_path

    return visual_data_path, video_payload_path, video_task_path, None


def write_video_base_image_outputs(
    visual_data: dict,
    image_payload: dict,
    task_create_response: dict,
    task_result_response: dict | None,
) -> tuple[Path, Path, Path, Path | None]:
    OUTPUT_DIR.mkdir(exist_ok=True)

    visual_data_path = OUTPUT_DIR / "video-base-image-visual-data.json"
    image_payload_path = OUTPUT_DIR / "video-base-image-request.json"
    image_task_path = OUTPUT_DIR / "video-base-image-task-create.json"
    image_result_path = OUTPUT_DIR / "video-base-image-task-result.json"

    visual_data_path.write_text(
        json.dumps(visual_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    image_payload_path.write_text(
        json.dumps(image_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    image_task_path.write_text(
        json.dumps(task_create_response, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if task_result_response is not None:
        image_result_path.write_text(
            json.dumps(task_result_response, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return visual_data_path, image_payload_path, image_task_path, image_result_path

    return visual_data_path, image_payload_path, image_task_path, None


def extract_result_urls(task_result_response: dict) -> list[str]:
    data = task_result_response.get("data", {})
    response_data = data.get("response", {})
    urls = response_data.get("resultUrls")
    if isinstance(urls, list):
        return [url for url in urls if isinstance(url, str) and url]

    result_json = data.get("resultJson")
    if isinstance(result_json, str) and result_json:
        try:
            parsed = json.loads(result_json)
        except json.JSONDecodeError:
            return []
        urls = parsed.get("resultUrls", [])
        if isinstance(urls, list):
            return [url for url in urls if isinstance(url, str) and url]

    return []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Собирает запрос для Claude/KIE из файлов проекта."
    )
    parser.add_argument(
        "--input",
        default=str(PROJECT_ROOT / "contracts" / "agent-input-template.json"),
        help="Путь к входному JSON.",
    )
    parser.add_argument(
        "--print-message",
        action="store_true",
        help="Показать итоговый user message целиком в консоли.",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Отправить собранный запрос в Claude API.",
    )
    parser.add_argument(
        "--text-provider",
        default="auto",
        choices=["auto", "anthropic", "kie"],
        help="Где генерировать текст: auto, anthropic или kie.",
    )
    parser.add_argument(
        "--send-image",
        action="store_true",
        help=f"После ответа Claude отправить image-промпт в {KIE_IMAGE_MODEL_LABEL}.",
    )
    parser.add_argument(
        "--send-video",
        action="store_true",
        help="После ответа Claude отправить video-промпт в выбранную видеомодель.",
    )
    parser.add_argument(
        "--video-provider",
        default="auto",
        choices=["auto", "veo", "hailuo", "kling", "minimax"],
        help="Какую видеомодель использовать: auto, veo, hailuo, kling или minimax.",
    )
    parser.add_argument(
        "--draft-status",
        default="draft",
        choices=["draft", "ready"],
        help="Статус черновика для vk_drafts: draft или ready.",
    )
    parser.add_argument(
        "--scheduled-for",
        default="",
        help="Плановая дата и время публикации. Пример: 2026-04-27T10:30:00+10:00",
    )
    return parser.parse_args()


def main() -> int:
    configure_console()
    args = parse_args()
    input_path = Path(args.input).resolve()

    if not input_path.exists():
        print(f"Ошибка: файл не найден: {input_path}", file=sys.stderr)
        return 1

    try:
        scheduled_for = normalize_scheduled_for(args.scheduled_for)
        data = load_input(input_path)
        user_message = build_user_message(data)
        rubric_lock = str(data.get("rubric_title") or data.get("post_type") or "")
        payload = build_claude_payload(user_message, rubric_lock=rubric_lock)
        user_message_path, payload_path = write_outputs(user_message, payload)
    except Exception as exc:  # noqa: BLE001
        print(f"Ошибка сборки запроса: {exc}", file=sys.stderr)
        return 1

    print("Готово.")
    print(f"Тип поста: {data['post_type']}")
    print(f"Файл user message: {user_message_path}")
    print(f"Файл payload для Claude: {payload_path}")

    if args.send:
        try:
            text_provider, text_api_key = resolve_text_provider(args.text_provider)
            print(f"Текстовый провайдер: {text_provider}")
            response_data = send_claude_request(payload, text_api_key, text_provider)
            response_json_path, response_text_path = write_response_outputs(
                response_data
            )
        except Exception as exc:  # noqa: BLE001
            print(f"Ошибка отправки в Claude: {exc}", file=sys.stderr)
            return 1

        print(f"Файл raw-ответа Claude: {response_json_path}")
        print(f"Файл текстового ответа: {response_text_path}")

        answer_text = read_text(response_text_path)
        clean_post_text = extract_vk_post_text(answer_text)
        clean_post_path = write_clean_post_output(clean_post_text)
        print(f"Файл чистого VK-поста: {clean_post_path}")
        clean_post_validation = validate_clean_post_text(clean_post_text, data)
        clean_post_validation_path = write_clean_post_validation_report(
            clean_post_text,
            clean_post_validation,
        )
        if not clean_post_validation["is_safe"]:
            raise RuntimeError(
                "Чистый VK-пост не прошёл проверку: "
                + "; ".join(clean_post_validation["errors"])
                + f". Файл проверки: {clean_post_validation_path}"
            )
        draft_visual_data: dict | None = None
        draft_image_url: str | None = None
        draft_video_url: str | None = None
        try:
            extracted_visual_data = extract_visual_data(answer_text)
            if extracted_visual_data.get("visual_type") != "unknown":
                draft_visual_data = extracted_visual_data
        except Exception:
            draft_visual_data = None

        supabase_output_files: dict[str, str] = {
            "claude_response_json": _relative_project_path(response_json_path),
            "claude_response_text": _relative_project_path(response_text_path),
            "vk_post_clean": _relative_project_path(clean_post_path),
        }

        api_key = ""
        if args.send_image or args.send_video:
            try:
                api_key = get_api_key()
            except Exception as exc:  # noqa: BLE001
                print(f"Ошибка получения KIE_API_KEY для визуала: {exc}", file=sys.stderr)
                return 1

        if args.send_image:
            try:
                if draft_visual_data is None:
                    raise RuntimeError("Не удалось извлечь визуальные данные из ответа Claude.")
                visual_data = draft_visual_data
                if visual_data["visual_type"] != "image":
                    raise RuntimeError(
                        f"Claude не выбрал формат image, поэтому {KIE_IMAGE_MODEL_LABEL} не запускается."
                    )
                if not visual_data["prompt_text"]:
                    raise RuntimeError(
                        "Не удалось извлечь image-промпт из ответа Claude."
                    )

                validation_report = validate_visual_prompt(visual_data)
                validation_report_path = write_visual_validation_report(
                    visual_data,
                    validation_report,
                )
                print(f"Файл проверки image-промпта: {validation_report_path}")
                if not validation_report["is_safe"]:
                    raise RuntimeError(
                        "Image-промпт не прошёл проверку на факты и безопасность. "
                        "Смотрите output/image-validation.json"
                    )

                image_payload = build_image_payload(visual_data)
                task_create_response = create_image_task(image_payload, api_key)
                task_id = task_create_response.get("data", {}).get("taskId", "")
                if not task_id:
                    raise RuntimeError(
                        "KIE не вернул taskId для генерации изображения."
                    )

                task_result_response = wait_for_task_result(task_id, api_key)
                (
                    visual_data_path,
                    image_payload_path,
                    image_task_path,
                    image_result_path,
                ) = write_image_outputs(
                    visual_data,
                    image_payload,
                    task_create_response,
                    task_result_response,
                )
                image_urls = extract_result_urls(task_result_response)
                if image_urls:
                    draft_image_url = image_urls[0]
                    supabase_output_files["image_urls"] = image_urls
                if image_result_path is not None:
                    supabase_output_files["image_result"] = _relative_project_path(
                        image_result_path
                    )
            except Exception as exc:  # noqa: BLE001
                print(f"Ошибка генерации изображения: {exc}", file=sys.stderr)
                return 1

            print(f"Файл визуальных данных: {visual_data_path}")
            print(f"Файл image payload: {image_payload_path}")
            print(f"Файл создания image task: {image_task_path}")
            if image_result_path is not None:
                print(f"Файл результата image task: {image_result_path}")

        if args.send_video:
            try:
                if draft_visual_data is None:
                    raise RuntimeError("Не удалось извлечь визуальные данные из ответа Claude.")
                visual_data = draft_visual_data
                if visual_data["visual_type"] != "video":
                    raise RuntimeError(
                        "Claude не выбрал формат video, поэтому видео-ветка не запускается."
                    )
                if not visual_data["video_prompt_text"]:
                    raise RuntimeError(
                        "Не удалось извлечь video-промпт из ответа Claude."
                    )

                selected_video_provider = args.video_provider
                if selected_video_provider == "auto":
                    selected_video_provider = visual_data.get("video_model", "veo")

                video_route = visual_data.get("video_route", "text_to_video")
                if visual_data.get("video_has_text_overlay"):
                    video_route = "image_to_video"

                base_image_url = None
                if video_route == "image_to_video":
                    if not visual_data["image_prompt_text"]:
                        raise RuntimeError(
                            f"Для маршрута image_to_video не найден image prompt для {KIE_IMAGE_MODEL_LABEL}."
                        )

                    base_image_visual_data = {
                        "prompt_text": visual_data["image_prompt_text"],
                        "aspect_ratio": visual_data.get("image_prompt_aspect_ratio", "9:16"),
                        "resolution": visual_data.get("image_prompt_resolution", "1K"),
                        "output_format": visual_data.get("image_prompt_output_format", "png"),
                    }
                    base_image_validation = validate_visual_prompt(base_image_visual_data)
                    base_image_validation_path = write_visual_validation_report(
                        base_image_visual_data,
                        base_image_validation,
                        filename="video-base-image-validation.json",
                    )
                    print(f"Файл проверки base image: {base_image_validation_path}")
                    if not base_image_validation["is_safe"]:
                        raise RuntimeError(
                            "Base image-промпт для видео не прошёл проверку. "
                            "Смотрите output/video-base-image-validation.json"
                        )

                    base_image_payload = build_base_image_payload(visual_data)
                    base_image_task_create = create_image_task(base_image_payload, api_key)
                    base_image_task_id = base_image_task_create.get("data", {}).get("taskId", "")
                    if not base_image_task_id:
                        raise RuntimeError(
                            "KIE не вернул taskId для base image перед видео."
                        )

                    base_image_task_result = wait_for_task_result(base_image_task_id, api_key)
                    (
                        video_base_image_visual_data_path,
                        video_base_image_payload_path,
                        video_base_image_task_path,
                        video_base_image_result_path,
                    ) = write_video_base_image_outputs(
                        visual_data,
                        base_image_payload,
                        base_image_task_create,
                        base_image_task_result,
                    )
                    base_image_urls = extract_result_urls(base_image_task_result)
                    if not base_image_urls:
                        raise RuntimeError(
                            "Не удалось извлечь URL base image для video pipeline."
                        )
                    base_image_url = base_image_urls[0]
                    draft_image_url = base_image_url

                video_payload = build_video_payload(
                    visual_data,
                    selected_video_provider,
                    base_image_url=base_image_url,
                )
                video_task_create_response = create_video_task(video_payload, api_key)
                task_id = video_task_create_response.get("data", {}).get("taskId", "")
                if not task_id:
                    raise RuntimeError(
                        "KIE не вернул taskId для генерации видео."
                    )

                video_task_result = wait_for_any_video_result(
                    task_id,
                    api_key,
                    selected_video_provider,
                )
                (
                    video_visual_data_path,
                    video_payload_path,
                    video_task_path,
                    video_result_path,
                ) = write_video_outputs(
                    visual_data,
                    video_payload,
                    video_task_create_response,
                    video_task_result,
                )
                video_urls = extract_result_urls(video_task_result)
                if video_urls:
                    draft_video_url = video_urls[0]
                if video_result_path is not None:
                    supabase_output_files["video_result"] = _relative_project_path(
                        video_result_path
                    )
            except Exception as exc:  # noqa: BLE001
                print(f"Ошибка генерации видео: {exc}", file=sys.stderr)
                return 1

            print(f"Маршрут видео: {video_route}")
            print(f"Video provider: {selected_video_provider}")
            if video_route == "image_to_video":
                print(f"Файл base image visual data: {video_base_image_visual_data_path}")
                print(f"Файл base image payload: {video_base_image_payload_path}")
                print(f"Файл base image task: {video_base_image_task_path}")
                if video_base_image_result_path is not None:
                    print(f"Файл результата base image: {video_base_image_result_path}")
                print(f"URL base image: {base_image_url}")
            print(f"Файл видео-данных: {video_visual_data_path}")
            print(f"Файл video payload: {video_payload_path}")
            print(f"Файл создания video task: {video_task_path}")
            if video_result_path is not None:
                print(f"Файл результата video task: {video_result_path}")

        try_log_agent_run_to_supabase(
            post_type=data["post_type"],
            input_path=input_path,
            input_data=data,
            send_image=args.send_image,
            send_video=args.send_video,
            output_files=supabase_output_files,
        )
        try_save_vk_draft_to_supabase(
            input_data=data,
            post_text=clean_post_text,
            visual_data=draft_visual_data,
            image_url=draft_image_url,
            video_url=draft_video_url,
            draft_status=args.draft_status,
            scheduled_for=scheduled_for,
            output_files=supabase_output_files,
        )

    if args.print_message:
        print("\n===== BEGIN USER MESSAGE =====\n")
        print(user_message)
        print("\n===== END USER MESSAGE =====")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
