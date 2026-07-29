# -*- coding: utf-8 -*-
"""Скачивает картинки для rubrics-transfer-links: из URL или через KIE по промпту."""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
MEDIA_DIR = PROJECT_ROOT / "output" / "rubrics-media"
HTML_FILE = PROJECT_ROOT / "output" / "rubrics-transfer-links.html"
KIE_IMAGE_TASK_URL = "https://api.kie.ai/api/v1/jobs/createTask"
KIE_TASK_INFO_URL = "https://api.kie.ai/api/v1/jobs/recordInfo?taskId={task_id}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# rubric_key, local filename, prompt file (optional), result json (optional), aspect ratio
ASSETS = [
    ("razbor", "razbor-post - Nano Banana Pro.png", "output/razbor-post-visual-prompt-restore.txt", "output/test-case-retest-visual-v2-task-result.json", "4:5"),
    ("law_review", "law-review-post - Nano Banana Pro.png", "output/law-review-post-visual-prompt-restore.txt", "output/test-law-review-task-result.json", "4:5"),
    ("case-post", "case-post - Nano Banana Pro.png", "output/case-post-usn-22-vychet-visual-prompt.txt", "output/case-post-usn-22-vychet-visual-v2-result.json", "4:5"),
    ("case-cover", "case-article-cover - Nano Banana Pro.png", "output/article-cover-case-usn-22-vychet-prompt-v2.txt", "output/article-cover-case-usn-22-vychet-v2-result.json", "16:9"),
    ("expert-post", "expert-post - Nano Banana Pro.png", "output/expert-post-zero-rate-nds-visual-prompt-v4-color-restored.txt", "output/expert-post-zero-rate-nds-visual-v4-result.json", "4:5"),
    ("expert-cover", "expert-article-cover - Nano Banana Pro.png", "output/expert-article-zero-rate-nds-cover-prompt.txt", "output/expert-article-zero-rate-nds-cover-result.json", "16:9"),
    ("calculation-post", "calculation-post - Nano Banana Pro.png", "output/calculation-post-separate-accounting-medical-and-22-visual-prompt.txt", "output/calculation-post-separate-accounting-medical-and-22-visual-result.json", "4:5"),
    ("calculation-cover", "calculation-article-cover - Nano Banana Pro.png", "output/calculation-article-separate-accounting-medical-and-22-cover-prompt.txt", "output/calculation-article-separate-accounting-medical-and-22-cover-result.json", "16:9"),
    ("serial-post", "serial-s1-ep01-post - Nano Banana Pro.png", "output/serial-yumor-s1-ep01-visual-prompt-v2.txt", "output/serial-yumor-s1-ep01-visual-v2-result.json", "4:5"),
    ("poll-post", "poll-post - Nano Banana Pro.png", "output/poll-post-nds-reporting-visual-prompt.txt", "output/poll-post-nds-reporting-visual-result.json", "4:5"),
    ("checklist-post", "checklist-post - Nano Banana Pro.png", "output/checklist-post-vychet-confirmation-visual-prompt.txt", "output/checklist-post-vychet-confirmation-visual-result.json", "4:5"),
    ("announcement-post", "article-announcement-post - Nano Banana Pro.png", "output/article-announcement-separate-accounting-medical-and-22-visual-prompt.txt", "output/article-announcement-separate-accounting-medical-and-22-visual-result.json", "4:5"),
]

# old tempfile URL substring -> local filename (for HTML replace)
URL_TO_FILE: dict[str, str] = {}


def load_dotenv() -> None:
    if not ENV_FILE.exists():
        return
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def extract_url_from_result_json(path: Path) -> str:
    if not path.exists():
        return ""
    data = json.loads(path.read_text(encoding="utf-8"))
    result_json = data.get("data", {}).get("resultJson", "")
    if not result_json:
        return ""
    parsed = json.loads(result_json)
    urls = parsed.get("resultUrls", [])
    return str(urls[0]) if urls else ""


def http_ok(url: str) -> bool:
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return 200 <= resp.status < 400
    except Exception:
        return False


def download_file(url: str, dest: Path) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        if len(data) < 1000:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return True
    except Exception as exc:
        print(f"  download fail: {exc}")
        return False


def create_task(prompt: str, api_key: str, aspect_ratio: str) -> str:
    payload = {
        "model": "gpt-image-2-text-to-image",
        "input": {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "resolution": "1K",
        },
    }
    req = urllib.request.Request(
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
    with urllib.request.urlopen(req, timeout=120) as response:
        data = json.loads(response.read().decode("utf-8"))
    task_id = data.get("data", {}).get("taskId") or data.get("taskId")
    if not task_id:
        raise RuntimeError(json.dumps(data, ensure_ascii=False)[:500])
    return str(task_id)


def wait_image_url(task_id: str, api_key: str) -> str:
    for index in range(180):
        time.sleep(5)
        req = urllib.request.Request(
            KIE_TASK_INFO_URL.format(task_id=task_id),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "User-Agent": UA,
            },
        )
        with urllib.request.urlopen(req, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
        state = data.get("data", {}).get("state", "")
        print(f"    [{index + 1}] state={state}")
        if state == "success":
            result_json = data.get("data", {}).get("resultJson", "")
            if result_json:
                urls = json.loads(result_json).get("resultUrls", [])
                if urls:
                    return str(urls[0])
        if state in {"failed", "error"}:
            raise RuntimeError(json.dumps(data, ensure_ascii=False)[:800])
    raise TimeoutError(task_id)


def regenerate(prompt_path: Path, api_key: str, aspect_ratio: str) -> str:
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    task_id = create_task(prompt, api_key, aspect_ratio)
    print(f"    task_id={task_id}")
    return wait_image_url(task_id, api_key)


def patch_html(url_map: dict[str, str]) -> None:
    if not HTML_FILE.exists():
        return
    html = HTML_FILE.read_text(encoding="utf-8")
    changed = 0
    for old_url, filename in url_map.items():
        rel = f"rubrics-media/{filename}"
        if old_url in html:
            html = html.replace(old_url, rel)
            changed += html.count(rel)  # rough
            print(f"  html: {filename}")
    HTML_FILE.write_text(html, encoding="utf-8")
    print(f"HTML updated ({len(url_map)} url replacements)")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    api_key = os.environ.get("KIE_API_KEY", "").strip()
    if not api_key:
        print("KIE_API_KEY не найден в .env", file=sys.stderr)
        return 1

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    url_map: dict[str, str] = {}

    for key, filename, prompt_rel, result_rel, aspect in ASSETS:
        dest = MEDIA_DIR / filename
        print(f"\n== {key} ==")
        if dest.exists() and dest.stat().st_size > 1000:
            print(f"  skip (already exists): {dest.name}")
            continue

        old_url = extract_url_from_result_json(PROJECT_ROOT / result_rel)
        if old_url:
            URL_TO_FILE[old_url] = filename
            if http_ok(old_url) and download_file(old_url, dest):
                print(f"  downloaded from old url -> {dest.name}")
                url_map[old_url] = filename
                continue
            print("  old tempfile url expired (404)")

        if not prompt_rel:
            print("  ERROR: no prompt file, cannot regenerate")
            continue

        prompt_path = PROJECT_ROOT / prompt_rel
        if not prompt_path.exists():
            print(f"  ERROR: prompt missing: {prompt_rel}")
            continue

        print(f"  regenerating via KIE ({aspect})...")
        try:
            new_url = regenerate(prompt_path, api_key, aspect)
            if old_url:
                url_map[old_url] = filename
            if download_file(new_url, dest):
                print(f"  saved -> {dest.name}")
                # update link file
                link_guess = result_rel.replace("-result.json", "-link.txt").replace("-task-result.json", "-link.txt")
                link_path = PROJECT_ROOT / link_guess
                if link_path.exists():
                    link_path.write_text(f"Локальный файл:\noutput/rubrics-media/{filename}\n\nВременный URL KIE:\n{new_url}\n", encoding="utf-8")
            else:
                print("  ERROR: could not save regenerated image")
        except Exception as exc:
            print(f"  ERROR regenerate: {exc}")

    # patch HTML for all known old urls from result jsons
    for _, filename, _, result_rel, _ in ASSETS:
        old_url = extract_url_from_result_json(PROJECT_ROOT / result_rel)
        if old_url and (MEDIA_DIR / filename).exists():
            url_map[old_url] = filename

    if url_map:
        patch_html(url_map)

    manifest = MEDIA_DIR / "manifest.json"
    manifest.write_text(
        json.dumps(
            [{"file": f.name, "path": f"output/rubrics-media/{f.name}"} for f in sorted(MEDIA_DIR.glob("*.png"))],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nDone. Files in {MEDIA_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
