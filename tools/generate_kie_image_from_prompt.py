"""Генерация одной картинки через KIE GPT Image 2 по prompt-файлу."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib import request


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
KIE_IMAGE_TASK_URL = "https://api.kie.ai/api/v1/jobs/createTask"
KIE_TASK_INFO_URL = "https://api.kie.ai/api/v1/jobs/recordInfo?taskId={task_id}"
KIE_IMAGE_MODEL = "gpt-image-2-text-to-image"
KIE_IMAGE_MODEL_LABEL = "GPT Image 2"
POLL_INTERVAL_SEC = 5
MAX_WAIT_ITERATIONS = 180  # до ~15 минут (GPT Image 2 часто дольше 5 мин)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def load_dotenv_file() -> None:
    if not ENV_FILE.exists():
        return
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def create_task(prompt: str, api_key: str, aspect_ratio: str) -> str:
    payload = {
        "model": KIE_IMAGE_MODEL,
        "input": {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "resolution": "1K",
        },
    }
    req = request.Request(
        KIE_IMAGE_TASK_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": UA,
        },
        method="POST",
    )
    with request.urlopen(req, timeout=120) as response:
        data = json.loads(response.read().decode("utf-8"))
    task_id = data.get("data", {}).get("taskId") or data.get("taskId")
    if not task_id:
        raise RuntimeError(f"KIE не вернул taskId: {json.dumps(data, ensure_ascii=False)[:500]}")
    return task_id


def extract_image_url(data: dict) -> str:
    result_json = data.get("data", {}).get("resultJson", "")
    if result_json:
        parsed = json.loads(result_json)
        urls = parsed.get("resultUrls", [])
        if urls:
            return str(urls[0])

    output = data.get("data", {}).get("output", {})
    if isinstance(output, dict):
        for value in output.values():
            if isinstance(value, str) and value.startswith("http"):
                return value
    if isinstance(output, list):
        for value in output:
            if isinstance(value, str) and value.startswith("http"):
                return value
    return ""


def wait_result(task_id: str, api_key: str) -> tuple[dict, str]:
    for index in range(MAX_WAIT_ITERATIONS):
        time.sleep(POLL_INTERVAL_SEC)
        req = request.Request(
            KIE_TASK_INFO_URL.format(task_id=task_id),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "User-Agent": UA,
            },
            method="GET",
        )
        with request.urlopen(req, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
        state = data.get("data", {}).get("state", "")
        print(f"[{index + 1}] state={state}")
        if state == "success":
            return data, extract_image_url(data)
        if state in {"failed", "error"}:
            raise RuntimeError(json.dumps(data, ensure_ascii=False)[:1000])
    raise TimeoutError("KIE image generation timeout")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Генерация картинки KIE по prompt-файлу.")
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-link", required=True)
    parser.add_argument("--aspect-ratio", default="", help="Например 1:1 или 16:9. Для article-cover авто: 16:9.")
    return parser.parse_args()


def infer_aspect_ratio(prompt_file: str, explicit_aspect_ratio: str) -> str:
    if explicit_aspect_ratio.strip():
        return explicit_aspect_ratio.strip()
    normalized = prompt_file.lower().replace("\\", "/")
    if "article-cover" in normalized or "обложка статьи" in normalized:
        return "16:9"
    return "1:1"


def main() -> int:
    args = parse_args()
    load_dotenv_file()
    api_key = os.environ.get("KIE_API_KEY", "").strip()
    if not api_key:
        print("Ошибка: KIE_API_KEY не найден в .env", file=sys.stderr)
        return 1

    prompt_path = (PROJECT_ROOT / args.prompt_file).resolve()
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    aspect_ratio = infer_aspect_ratio(args.prompt_file, args.aspect_ratio)
    print(f"aspect_ratio={aspect_ratio}")
    task_id = create_task(prompt, api_key, aspect_ratio)
    print(f"task_id={task_id}")
    result, image_url = wait_result(task_id, api_key)

    out_json = (PROJECT_ROOT / args.out_json).resolve()
    out_link = (PROJECT_ROOT / args.out_link).resolve()
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_link.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    out_link.write_text(f"Визуал {KIE_IMAGE_MODEL_LABEL}:\n{image_url}\n", encoding="utf-8")
    print(f"IMAGE_URL={image_url}")
    print(f"JSON={out_json}")
    print(f"LINK={out_link}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
