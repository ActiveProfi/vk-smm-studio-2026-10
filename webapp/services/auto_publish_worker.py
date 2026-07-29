"""Фоновый таймер: публикует ready-посты, у которых наступило время."""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

_log = logging.getLogger("auto_publish")
_started = False
_lock = threading.Lock()
# Последний прогон по каналу: {workspace_id: {at, published, checked, error}}
_LAST_RUN: dict[int, dict[str, Any]] = {}


def last_run(workspace_id: int) -> dict[str, Any] | None:
    return _LAST_RUN.get(int(workspace_id))


def _interval_sec() -> int:
    raw = (os.environ.get("AUTO_PUBLISH_INTERVAL_SEC") or "60").strip()
    try:
        return max(30, int(raw))
    except ValueError:
        return 60


def _tick(app) -> None:
    from webapp.models import Workspace
    from webapp.services import business as biz

    with app.app_context():
        channels = Workspace.query.filter_by(auto_publish_enabled=True, is_active=True).all()
        for ws in channels:
            try:
                result = biz.run_auto_publish_for_workspace(ws)
                _LAST_RUN[int(ws.id)] = {
                    "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "published": int(result.get("published") or 0),
                    "checked": int(result.get("checked") or 0),
                    "ok": bool(result.get("ok")),
                    "error": (result.get("error") or ""),
                    "errors": list(result.get("errors") or [])[:5],
                }
                pub = int(result.get("published") or 0)
                if pub:
                    _log.info(
                        "auto_publish ws=%s published=%s checked=%s",
                        ws.id,
                        pub,
                        result.get("checked"),
                    )
                elif not result.get("ok") and result.get("error"):
                    _log.warning("auto_publish ws=%s: %s", ws.id, result.get("error"))
            except Exception as exc:  # noqa: BLE001
                _LAST_RUN[int(ws.id)] = {
                    "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "published": 0,
                    "checked": 0,
                    "ok": False,
                    "error": str(exc),
                    "errors": [],
                }
                _log.exception("auto_publish ws=%s failed", ws.id)


def _loop(app) -> None:
    # Небольшая пауза после старта, чтобы БД успела подняться
    time.sleep(8)
    while True:
        try:
            _tick(app)
        except Exception:  # noqa: BLE001
            _log.exception("auto_publish tick failed")
        time.sleep(_interval_sec())


def start_auto_publish_worker(app) -> None:
    """Запустить фоновый поток один раз на процесс."""
    global _started
    with _lock:
        if _started:
            return
        # При debug+reloader не дублируем; у нас reloader обычно выключен
        if os.environ.get("WERKZEUG_RUN_MAIN") == "false":
            return
        _started = True
        t = threading.Thread(target=_loop, args=(app,), name="auto-publish", daemon=True)
        t.start()
        _log.info("auto_publish worker started, interval=%ss", _interval_sec())
