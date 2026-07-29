"""VseGPT: основной провайдер картинок; для текста — только резерв после KIE."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib import error, request

ENV_FILE = Path(__file__).resolve().parent / ".env"

VSEGPT_CHAT_URL = "https://api.vsegpt.ru/v1/chat/completions"
VSEGPT_ANTHROPIC_URL = "https://services.vsegpt.ru:3000/v1/messages"
VSEGPT_IMAGE_URL = "https://api.vsegpt.ru/v1/images/generations"

# Если картинка не готова за это время — пайплайн переключается на KIE.
DEFAULT_VSEGPT_IMAGE_TIMEOUT_SEC = 180

DEFAULT_USER_AGENT = "VK-SMM-Webapp/1.0"


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


def get_vsegpt_api_key(*, optional: bool = False) -> str:
    load_dotenv_file()
    api_key = os.environ.get("VSEGPT_API_KEY", "").strip()
    if not api_key and not optional:
        raise ValueError(
            "Не найден VSEGPT_API_KEY. Добавьте ключ в .env (личный кабинет vsegpt.ru)."
        )
    return api_key


def is_vsegpt_configured() -> bool:
    return bool(get_vsegpt_api_key(optional=True))


def get_vsegpt_text_model() -> str:
    return (
        os.environ.get("VSEGPT_TEXT_MODEL", "").strip()
        or "anthropic/claude-sonnet-4-6"
    )


def get_vsegpt_image_model() -> str:
    return os.environ.get("VSEGPT_IMAGE_MODEL", "").strip() or "dall-e-3"


def get_vsegpt_image_timeout_sec() -> int:
    load_dotenv_file()
    raw = os.environ.get("VSEGPT_IMAGE_TIMEOUT_SEC", "").strip()
    try:
        value = int(raw or DEFAULT_VSEGPT_IMAGE_TIMEOUT_SEC)
    except ValueError:
        value = DEFAULT_VSEGPT_IMAGE_TIMEOUT_SEC
    return max(30, value)


def _http_json(
    url: str,
    *,
    api_key: str,
    payload: dict | None = None,
    method: str = "POST",
    extra_headers: dict | None = None,
    timeout: int = 180,
    auth_bearer: bool = True,
) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": DEFAULT_USER_AGENT,
    }
    if auth_bearer:
        headers["Authorization"] = f"Bearer {api_key}"
    if extra_headers:
        headers.update(extra_headers)

    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = request.Request(url, data=body, method=method, headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} VseGPT: {err_body}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Сеть VseGPT: {exc}") from exc


def _anthropic_payload_to_openai(payload: dict, model: str) -> dict:
    messages: list[dict] = []
    system = (payload.get("system") or "").strip()
    if system:
        messages.append({"role": "system", "content": system})
    for msg in payload.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role") or "user"
        content = msg.get("content")
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(str(block.get("text") or ""))
            content = "\n".join(text_parts).strip()
        messages.append({"role": role, "content": str(content or "")})
    return {
        "model": model,
        "max_tokens": int(payload.get("max_tokens") or 3200),
        "messages": messages,
        "stream": False,
    }


def send_claude_via_vsegpt(payload: dict, api_key: str) -> dict:
    """Ответ в формате Anthropic (content[].text), совместим с extract_text_from_response."""
    model = get_vsegpt_text_model()
    anthropic_payload = dict(payload)
    anthropic_payload["model"] = model

    try:
        data = _http_json(
            VSEGPT_ANTHROPIC_URL,
            api_key=api_key,
            payload=anthropic_payload,
            extra_headers={"X-Api-Key": api_key},
            auth_bearer=False,
        )
        if data.get("content"):
            return data
    except RuntimeError:
        pass

    openai_payload = _anthropic_payload_to_openai(payload, model)
    data = _http_json(VSEGPT_CHAT_URL, api_key=api_key, payload=openai_payload)
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"VseGPT: пустой ответ chat/completions: {data}")
    message = choices[0].get("message") or {}
    text = (message.get("content") or "").strip()
    if not text:
        raise RuntimeError(f"VseGPT: нет текста в ответе: {data}")
    return {"content": [{"type": "text", "text": text}]}


def _image_size_params(aspect_ratio: str, model: str) -> dict:
    ar = (aspect_ratio or "4:5").strip()
    model_l = model.lower()
    if "imagen" in model_l or "flux" in model_l or "nano" in model_l:
        return {"aspect_ratio": ar}
    size_map = {
        "9:16": "1024x1792",
        "16:9": "1792x1024",
        "4:5": "1024x1792",
        "3:4": "1024x1792",
        "1:1": "1024x1024",
    }
    return {"size": size_map.get(ar, "1024x1024")}


def _extract_image_url(response: dict) -> str:
    data = response.get("data")
    if isinstance(data, list) and data:
        item = data[0]
        if isinstance(item, dict):
            url = (item.get("url") or "").strip()
            if url:
                return url
            b64 = (item.get("b64_json") or "").strip()
            if b64:
                raise RuntimeError(
                    "VseGPT вернул base64 вместо URL — укажите response_format=url в настройках модели."
                )
    url = (response.get("url") or "").strip()
    if url:
        return url
    raise RuntimeError(f"VseGPT: ссылка на картинку не найдена: {response}")


def generate_image_via_vsegpt(
    prompt: str,
    *,
    aspect_ratio: str = "4:5",
    api_key: str | None = None,
    timeout_sec: int | None = None,
) -> str:
    key = api_key or get_vsegpt_api_key()
    model = get_vsegpt_image_model()
    clean_prompt = re.sub(r"\s+", " ", (prompt or "").strip())
    if len(clean_prompt) > 3900:
        clean_prompt = clean_prompt[:3900].rstrip() + "…"

    payload: dict = {
        "model": model,
        "prompt": clean_prompt,
        "n": 1,
        "response_format": "url",
    }
    payload.update(_image_size_params(aspect_ratio, model))

    timeout = int(timeout_sec if timeout_sec is not None else get_vsegpt_image_timeout_sec())
    response = _http_json(
        VSEGPT_IMAGE_URL,
        api_key=key,
        payload=payload,
        timeout=max(30, timeout),
    )
    return _extract_image_url(response)
