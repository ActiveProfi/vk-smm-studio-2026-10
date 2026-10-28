"""Фоновые задания генерации с прогрессом для веб-интерфейса."""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_DIR = Path(__file__).resolve().parents[1] / "job_status"
_JOBS_DIR.mkdir(parents=True, exist_ok=True)

STEP_LABELS = {
    "queued": "В очереди…",
    "prepare": "Подготовка данных…",
    "relevance_check": "Проверка актуальности…",
    "approval_required": "Нужно подтверждение",
    "text_generation": "Генерация текста…",
    "content_plan": "ИИ-маркетолог составляет план…",
    "visual_prepare": "Идёт генерация визуала…",
    "image_gpt_image_2": "Идёт генерация визуала…",
    "video_kling": "Идёт генерация визуала… Kling",
    "video_minimax": "Идёт генерация визуала… MiniMax",
    "video_veo": "Идёт генерация визуала… Veo",
    "video_hailuo": "Идёт генерация визуала… Hailuo",
    "save_draft": "Сохранение черновика…",
    "done": "Готово",
    "error": "Ошибка",
}

STEP_PERCENTS = {
    "queued": 2,
    "prepare": 5,
    "relevance_check": 15,
    "approval_required": 18,
    "text_generation": 40,
    "content_plan": 55,
    "visual_prepare": 52,
    "image_gpt_image_2": 65,
    "video_kling": 82,
    "video_minimax": 82,
    "video_veo": 82,
    "video_hailuo": 82,
    "save_draft": 95,
    "done": 100,
    "error": 100,
}


def _job_path(job_id: str) -> Path:
    return _JOBS_DIR / f"{job_id}.json"


_SECRET_PAYLOAD_KEYS = {
    "vk_token",
    "vk_ads_token",
    "vk_ads_client_secret",
    "vk_ads_refresh_token",
    "client_secret",
    "password",
    "access_token",
    "refresh_token",
}


def _persist(job: dict) -> None:
    """Сохраняем статус на диск (чтобы не терять при опросе). Секреты в файл не пишем."""
    payload = dict(job.get("payload") or {})
    for key in _SECRET_PAYLOAD_KEYS:
        payload.pop(key, None)
    public = {
        "id": job["id"],
        "user_id": job["user_id"],
        "status": job["status"],
        "step": job["step"],
        "message": job["message"],
        "percent": job["percent"],
        "error": job.get("error") or "",
        "warning": job.get("warning") or "",
        "draft_id": job.get("draft_id"),
        "image_url": job.get("image_url") or "",
        "plan_items": job.get("plan_items") or [],
        "plan_meta": job.get("plan_meta") or {},
        "payload": payload,
        "log": list(job.get("log") or [])[-20:],
        "updated_at": job.get("updated_at"),
    }
    _job_path(job["id"]).write_text(
        json.dumps(public, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def create_job(user_id: int, payload: dict) -> str:
    job_id = uuid.uuid4().hex
    with _LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "user_id": user_id,
            "status": "running",
            "step": "queued",
            "message": STEP_LABELS["queued"],
            "percent": 2,
            "error": "",
            "draft_id": None,
            "warning": "",
            "plan_items": [],
            "plan_meta": {},
            "created_at": time.time(),
            "updated_at": time.time(),
            "payload": payload,
            "log": [{"step": "queued", "message": STEP_LABELS["queued"], "ts": time.time()}],
        }
        _persist(_JOBS[job_id])
    return job_id


def update_job(job_id: str, **fields) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        from webapp.services.http_guard import scrub_secrets

        for key in ("message", "error", "warning"):
            if key in fields and isinstance(fields[key], str):
                fields[key] = scrub_secrets(fields[key])
        job.update(fields)
        job["updated_at"] = time.time()
        step = fields.get("step")
        message = fields.get("message")
        if step or message:
            job["log"].append(
                {
                    "step": step or job.get("step"),
                    "message": message or job.get("message"),
                    "ts": time.time(),
                }
            )
            if len(job["log"]) > 40:
                job["log"] = job["log"][-40:]
        _persist(job)


def get_job(job_id: str, user_id: int | None = None) -> dict | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job:
            if user_id is not None and job.get("user_id") != user_id:
                return None
            return {
                "id": job["id"],
                "status": job["status"],
                "step": job["step"],
                "message": job["message"],
                "percent": job["percent"],
                "error": job.get("error") or "",
                "warning": job.get("warning") or "",
                "draft_id": job.get("draft_id"),
                "image_url": job.get("image_url") or "",
                "plan_items": list(job.get("plan_items") or []),
                "plan_meta": dict(job.get("plan_meta") or {}),
                "log": list(job.get("log") or []),
            }

    # После перезапуска сервера читаем с диска
    path = _job_path(job_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if user_id is not None and data.get("user_id") != user_id:
        return None
    return {
        "id": data.get("id"),
        "status": data.get("status"),
        "step": data.get("step"),
        "message": data.get("message"),
        "percent": data.get("percent"),
        "error": data.get("error") or "",
        "warning": data.get("warning") or "",
        "draft_id": data.get("draft_id"),
        "image_url": data.get("image_url") or "",
        "plan_items": list(data.get("plan_items") or []),
        "plan_meta": dict(data.get("plan_meta") or {}),
        "log": list(data.get("log") or []),
    }


def get_job_payload(job_id: str, user_id: int | None = None) -> dict | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job:
            if user_id is not None and job.get("user_id") != user_id:
                return None
            payload = job.get("payload")
            return dict(payload) if isinstance(payload, dict) else None

    path = _job_path(job_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if user_id is not None and data.get("user_id") != user_id:
        return None
    payload = data.get("payload")
    return dict(payload) if isinstance(payload, dict) else None


def set_job_payload(job_id: str, payload: dict) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job["payload"] = dict(payload)
        job["updated_at"] = time.time()
        _persist(job)


def make_progress_callback(job_id: str) -> Callable[[str, str | None], None]:
    def _cb(step: str, message: str | None = None) -> None:
        label = message or STEP_LABELS.get(step, step)
        percent = STEP_PERCENTS.get(step, 50)
        with _LOCK:
            job = _JOBS.get(job_id)
            if (
                job
                and (
                    step in ("visual_prepare", "image_gpt_image_2")
                    or str(step).startswith("video_")
                )
                and message
                and "прошло" in message
            ):
                cap = 92
                percent = min(int(job.get("percent") or percent) + 2, cap)
        update_job(
            job_id,
            step=step,
            message=label,
            percent=percent,
        )

    return _cb


def purge_old_jobs(max_age_sec: int = 24 * 60 * 60) -> int:
    """Удалить старые файлы заданий: в них бывают тексты постов и материалы."""
    removed = 0
    now = time.time()
    try:
        files = list(_JOBS_DIR.glob("*.json"))
    except OSError:
        return 0
    for path in files:
        try:
            if now - path.stat().st_mtime > max_age_sec:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed
