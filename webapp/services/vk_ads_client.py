"""Клиент VK Реклама (Ads API v2, ads.vk.com / ads.vk.ru).

Список кампаний + автообновление access_token через refresh_token.
Секреты только в .env / настройках канала.
"""
from __future__ import annotations

import json
import os
import ssl
import threading
import time
from pathlib import Path
from typing import Any
from urllib import error, parse, request


BASE_URL = "https://ads.vk.com/api/v2"
OAUTH_TOKEN_URL = "https://ads.vk.ru/api/v2/oauth2/token.json"

# Обновлять access_token за N секунд до истечения (запас ~30 мин)
REFRESH_SKEW_SEC = 30 * 60

STATUS_LABELS_RU = {
    "active": "Запущена",
    "blocked": "Остановлена",
    "deleted": "Удалена",
}

_refresh_lock = threading.Lock()


def _ssl_context():
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


def _project_root() -> Path:
    # webapp/services/vk_ads_client.py → корень проекта «VK для ИНТЕНСИВОВ»
    return Path(__file__).resolve().parents[2]


def _env_path() -> Path:
    return _project_root() / ".env"


def _friendly_http_error(code: int, body: str) -> str:
    text = (body or "").strip()
    short = text[:400] if text else ""
    if code == 401:
        return (
            "Токен VK Реклама недействителен или истёк. "
            "Если в .env есть VK_ADS_REFRESH_TOKEN — приложение обновит его само. "
            "Иначе снова запустите tools/get_vk_ads_token.ps1."
            + (f" Ответ: {short}" if short else "")
        )
    if code == 403:
        return (
            "Нет прав на этот кабинет рекламы. Проверьте, что токен выдан для нужного аккаунта."
            + (f" Ответ: {short}" if short else "")
        )
    if code == 429:
        return "Слишком много запросов к API VK Реклама. Подождите минуту и обновите страницу."
    return f"VK Реклама API ошибка HTTP {code}" + (f": {short}" if short else "")


def _set_env_keys(updates: dict[str, str]) -> None:
    """Пишет ключи в os.environ и в файл .env (если файл есть)."""
    for key, value in updates.items():
        if value is None:
            continue
        os.environ[key] = str(value)

    path = _env_path()
    if not path.is_file():
        return

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return

    keys_done = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            out.append(line)
            continue
        key, _, _rest = line.partition("=")
        key = key.strip()
        if key in updates:
            out.append(f"{key}={updates[key]}")
            keys_done.add(key)
        else:
            out.append(line)

    for key, value in updates.items():
        if key not in keys_done:
            out.append(f"{key}={value}")

    try:
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
    except Exception:
        # Процесс всё равно держит свежие значения в os.environ
        pass


def env_ads_credentials() -> dict:
    """Значения VK Реклама из окружения / .env."""
    return {
        "client_id": (os.environ.get("VK_ADS_CLIENT_ID") or "").strip(),
        "client_secret": (os.environ.get("VK_ADS_CLIENT_SECRET") or "").strip(),
        "access_token": resolve_ads_token(""),
        "refresh_token": (os.environ.get("VK_ADS_REFRESH_TOKEN") or "").strip(),
        "account_id": (os.environ.get("VK_ADS_ACCOUNT_ID") or "").strip(),
        "expires_at": (os.environ.get("VK_ADS_TOKEN_EXPIRES_AT") or "").strip(),
    }


def resolve_ads_token(workspace_token: str = "") -> str:
    """Токен канала, иначе VK_ADS_TOKEN / VK_ADS_ACCESS_TOKEN из .env."""
    token = (workspace_token or "").strip()
    if token:
        return token
    return (
        (os.environ.get("VK_ADS_TOKEN") or "").strip()
        or (os.environ.get("VK_ADS_ACCESS_TOKEN") or "").strip()
    )


def _token_expires_soon() -> bool:
    raw = (os.environ.get("VK_ADS_TOKEN_EXPIRES_AT") or "").strip()
    if not raw:
        # Срока нет — не трогаем заранее, обновим по 401
        return False
    try:
        expires_at = int(float(raw))
    except (TypeError, ValueError):
        return False
    return time.time() >= (expires_at - REFRESH_SKEW_SEC)


def _oauth_token_request(body: dict[str, str]) -> dict:
    encoded = parse.urlencode(body).encode("utf-8")
    req = request.Request(
        OAUTH_TOKEN_URL,
        data=encoded,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    ctx = _ssl_context()
    try:
        with request.urlopen(req, timeout=60, context=ctx) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        err_body = ""
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise RuntimeError(
            f"Не удалось обновить токен VK Реклама (HTTP {exc.code}). "
            f"{err_body[:300] or 'Проверьте client_id, client_secret и refresh_token.'}"
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(f"Нет связи с OAuth VK Реклама: {exc.reason}") from exc


def _apply_token_response(data: dict) -> str:
    access = str(data.get("access_token") or "").strip()
    if not access:
        raise RuntimeError("VK Реклама не вернула access_token при обновлении.")

    refresh = str(data.get("refresh_token") or "").strip()
    try:
        expires_in = int(data.get("expires_in") or 86400)
    except (TypeError, ValueError):
        expires_in = 86400
    expires_at = str(int(time.time()) + max(60, expires_in))

    updates = {
        "VK_ADS_TOKEN": access,
        "VK_ADS_ACCESS_TOKEN": access,
        "VK_ADS_TOKEN_EXPIRES_AT": expires_at,
    }
    if refresh:
        updates["VK_ADS_REFRESH_TOKEN"] = refresh
    _set_env_keys(updates)
    return access


def refresh_access_token() -> str:
    """Обновить access_token через refresh_token (OAuth2)."""
    creds = env_ads_credentials()
    client_id = creds["client_id"]
    client_secret = creds["client_secret"]
    refresh = creds["refresh_token"]
    if not client_id or not client_secret:
        raise RuntimeError(
            "Для автообновления токена нужны VK_ADS_CLIENT_ID и VK_ADS_CLIENT_SECRET в .env."
        )
    if not refresh:
        raise RuntimeError(
            "Нет VK_ADS_REFRESH_TOKEN в .env. Запустите tools/get_vk_ads_token.ps1 один раз."
        )

    data = _oauth_token_request(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": client_id,
            "client_secret": client_secret,
        }
    )
    return _apply_token_response(data)


def obtain_access_token_client_credentials() -> str:
    """Выписать новый токен по client_id/secret (если refresh недоступен)."""
    creds = env_ads_credentials()
    client_id = creds["client_id"]
    client_secret = creds["client_secret"]
    if not client_id or not client_secret:
        raise RuntimeError("Нужны VK_ADS_CLIENT_ID и VK_ADS_CLIENT_SECRET в .env.")

    data = _oauth_token_request(
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
    )
    return _apply_token_response(data)


def ensure_access_token(preferred: str = "") -> str:
    """
    Вернуть рабочий access_token.
    Если срок подходит к концу или токена нет — обновить через refresh_token.
    """
    with _refresh_lock:
        current = resolve_ads_token(preferred)
        needs_refresh = (not current) or _token_expires_soon()
        if not needs_refresh:
            return current

        try:
            return refresh_access_token()
        except Exception:
            # refresh нет / сломан — пробуем client_credentials
            try:
                return obtain_access_token_client_credentials()
            except Exception:
                if current:
                    return current
                raise


def api_get(
    path: str,
    token: str = "",
    params: dict | None = None,
    timeout: int = 60,
    *,
    auto_refresh: bool = True,
) -> Any:
    """GET к ads.vk.com/api/v2/... с Bearer-токеном и автообновлением при 401."""
    token = ensure_access_token(token) if auto_refresh else (token or "").strip()
    if not token:
        raise ValueError(
            "Не задан токен VK Реклама. Заполните .env (VK_ADS_TOKEN) "
            "или блок «Подключение ВК Реклама» в настройках канала."
        )

    query = ""
    if params:
        clean = {k: v for k, v in params.items() if v is not None and v != ""}
        if clean:
            query = "?" + parse.urlencode(clean)
    url = f"{BASE_URL}{path}{query}"

    def _once(access: str) -> Any:
        req = request.Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Bearer {access}",
                "Accept": "application/json",
            },
        )
        ctx = _ssl_context()
        with request.urlopen(req, timeout=timeout, context=ctx) as response:
            raw = response.read().decode("utf-8")
            if not raw:
                return {}
            return json.loads(raw)

    try:
        return _once(token)
    except error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        if auto_refresh and exc.code == 401:
            with _refresh_lock:
                try:
                    new_token = refresh_access_token()
                except Exception:
                    try:
                        new_token = obtain_access_token_client_credentials()
                    except Exception as refresh_exc:
                        raise RuntimeError(_friendly_http_error(exc.code, body)) from refresh_exc
            try:
                return _once(new_token)
            except error.HTTPError as exc2:
                body2 = ""
                try:
                    body2 = exc2.read().decode("utf-8", errors="replace")
                except Exception:
                    pass
                raise RuntimeError(_friendly_http_error(exc2.code, body2)) from exc2
        raise RuntimeError(_friendly_http_error(exc.code, body)) from exc
    except error.URLError as exc:
        raise RuntimeError(f"Не удалось связаться с VK Реклама: {exc.reason}") from exc


def _parse_token_response(data: dict) -> dict:
    access = str(data.get("access_token") or "").strip()
    if not access:
        raise RuntimeError("VK Реклама не вернула access_token.")
    refresh = str(data.get("refresh_token") or "").strip()
    try:
        expires_in = int(data.get("expires_in") or 86400)
    except (TypeError, ValueError):
        expires_in = 86400
    expires_at = str(int(time.time()) + max(60, expires_in))
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_in": expires_in,
        "expires_at": expires_at,
    }


def obtain_tokens_raw(client_id: str, client_secret: str) -> dict:
    """Получить access/refresh по Client Credentials (для подключения кабинета канала)."""
    client_id = (client_id or "").strip()
    client_secret = (client_secret or "").strip()
    if not client_id or not client_secret:
        raise ValueError("Нужны client_id и client_secret.")
    data = _oauth_token_request(
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
    )
    return _parse_token_response(data)


def ensure_workspace_access_token(ws) -> str:
    """Рабочий access_token для конкретного канала (хранение в Workspace)."""
    from webapp.models import db
    from webapp.services.secrets_box import reveal, seal

    with _refresh_lock:
        current = reveal(getattr(ws, "vk_ads_token", None))
        expires_raw = (getattr(ws, "vk_ads_token_expires_at", None) or "").strip()
        soon = False
        if expires_raw:
            try:
                soon = time.time() >= (int(float(expires_raw)) - REFRESH_SKEW_SEC)
            except (TypeError, ValueError):
                soon = False
        if current and not soon:
            return current

        client_id = (getattr(ws, "vk_ads_client_id", None) or "").strip()
        client_secret = reveal(getattr(ws, "vk_ads_client_secret", None))
        refresh = reveal(getattr(ws, "vk_ads_refresh_token", None))

        if not client_id or not client_secret:
            if current:
                return current
            return ensure_access_token("")

        try:
            if refresh:
                data = _oauth_token_request(
                    {
                        "grant_type": "refresh_token",
                        "refresh_token": refresh,
                        "client_id": client_id,
                        "client_secret": client_secret,
                    }
                )
            else:
                data = _oauth_token_request(
                    {
                        "grant_type": "client_credentials",
                        "client_id": client_id,
                        "client_secret": client_secret,
                    }
                )
            tokens = _parse_token_response(data)
            ws.vk_ads_token = seal(tokens["access_token"])
            if tokens.get("refresh_token"):
                ws.vk_ads_refresh_token = seal(tokens["refresh_token"])
            ws.vk_ads_token_expires_at = tokens["expires_at"]
            ws.vk_ads_status = "connected"
            ws.vk_ads_last_error = ""
            db.session.add(ws)
            db.session.commit()
            return tokens["access_token"]
        except Exception as exc:
            if current:
                return current
            ws.vk_ads_status = "error"
            ws.vk_ads_last_error = str(exc)[:500]
            try:
                db.session.add(ws)
                db.session.commit()
            except Exception:
                db.session.rollback()
            raise


def _extract_base_metrics(blob: Any) -> dict:
    """Достать spent/shows/clicks из разных форм ответа statistics."""
    if not isinstance(blob, dict):
        return {}
    base = blob.get("base") if isinstance(blob.get("base"), dict) else blob
    if not isinstance(base, dict):
        return {}
    spent = _as_float(base.get("spent"))
    shows = base.get("shows")
    if shows is None:
        shows = base.get("impressions")
    clicks = base.get("clicks")
    try:
        shows_i = int(shows) if shows is not None else None
    except (TypeError, ValueError):
        shows_i = None
    try:
        clicks_i = int(clicks) if clicks is not None else None
    except (TypeError, ValueError):
        clicks_i = None
    ctr = _as_float(base.get("ctr"))
    if ctr is None and shows_i and clicks_i is not None and shows_i > 0:
        ctr = round(100.0 * clicks_i / shows_i, 2)
    return {"spent": spent, "shows": shows_i, "clicks": clicks_i, "ctr": ctr}


def get_period_summary(*, token: str, date_from: str, date_to: str) -> dict:
    """
    Сводка кабинета за период: spent / shows / clicks.
    Пробуем summary по ad_plans, иначе суммируем day.
    """
    token = (token or "").strip()
    if not token:
        raise ValueError("Нет токена VK Реклама для статистики.")

    warning = ""
    totals = {"spent": 0.0, "shows": 0, "clicks": 0}
    found = False

    def _add_metrics(m: dict) -> None:
        nonlocal found
        if not m:
            return
        found = True
        if m.get("spent") is not None:
            totals["spent"] += float(m["spent"])
        if m.get("shows") is not None:
            totals["shows"] += int(m["shows"])
        if m.get("clicks") is not None:
            totals["clicks"] += int(m["clicks"])

    # 1) summary
    try:
        data = api_get(
            "/statistics/ad_plans/summary.json",
            token,
            params={"date_from": date_from, "date_to": date_to, "metrics": "base"},
            auto_refresh=False,
        )
        items = data.get("items") if isinstance(data, dict) else None
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                total = it.get("total") if isinstance(it.get("total"), dict) else it
                _add_metrics(_extract_base_metrics(total))
    except Exception as exc:  # noqa: BLE001
        warning = str(exc)

    # 2) day fallback
    if not found:
        try:
            data = api_get(
                "/statistics/ad_plans/day.json",
                token,
                params={"date_from": date_from, "date_to": date_to, "metrics": "base"},
                auto_refresh=False,
            )
            items = data.get("items") if isinstance(data, dict) else None
            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    rows = it.get("rows")
                    if isinstance(rows, list):
                        for row in rows:
                            if isinstance(row, dict):
                                _add_metrics(_extract_base_metrics(row))
                    else:
                        _add_metrics(_extract_base_metrics(it.get("total") or it))
            warning = ""
        except Exception as exc:  # noqa: BLE001
            if not warning:
                warning = str(exc)

    if not found:
        return {
            "spent": None,
            "shows": None,
            "clicks": None,
            "ctr": None,
            "warning": warning
            or "Статистика за период недоступна (пустой кабинет или нет прав metrics).",
        }

    ctr = None
    if totals["shows"] > 0:
        ctr = round(100.0 * totals["clicks"] / totals["shows"], 2)
    return {
        "spent": round(totals["spent"], 2),
        "shows": totals["shows"],
        "clicks": totals["clicks"],
        "ctr": ctr,
        "warning": warning,
    }


def _as_float(value) -> float | None:
    if value is None or value == "" or value == -1 or value == "-1":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_plan(item: dict) -> dict:
    status = str(item.get("status") or "").strip().lower() or "—"
    return {
        "id": item.get("id"),
        "name": (item.get("name") or f"Кампания {item.get('id')}").strip(),
        "status": status,
        "status_label": STATUS_LABELS_RU.get(status, status),
        "objective": item.get("objective") or "",
        "date_start": item.get("date_start") or "",
        "date_end": item.get("date_end") or "",
        "budget_limit": _as_float(item.get("budget_limit")),
        "budget_limit_day": _as_float(item.get("budget_limit_day")),
    }


def test_connection(*, token: str = "", workspace=None) -> dict:
    """Проверка токена: короткий запрос списка кампаний."""
    if workspace is not None:
        access = ensure_workspace_access_token(workspace)
    else:
        access = (token or "").strip() or ensure_access_token("")
    data = api_get(
        "/ad_plans.json",
        access,
        params={
            "fields": "id,name,status",
            "limit": 1,
            "_status__ne": "deleted",
        },
        auto_refresh=False,
    )
    items = data.get("items") if isinstance(data, dict) else None
    count = len(items) if isinstance(items, list) else 0
    return {
        "ok": True,
        "message": (
            "Кабинет VK Реклама отвечает. Токен принят."
            + (
                " Найдена хотя бы одна кампания."
                if count
                else " Кампаний пока не видно (или все удалены)."
            )
            + " Автообновление access_token включено."
        ),
        "sample_count": count,
        "access_token": access,
    }


def get_campaigns(
    *,
    token: str = "",
    include_deleted: bool = False,
    limit: int = 50,
    workspace=None,
) -> dict:
    """Список кампаний (ad_plans)."""
    if workspace is not None:
        access = ensure_workspace_access_token(workspace)
    else:
        access = (token or "").strip() or ensure_access_token("")
    limit = max(1, min(int(limit or 50), 100))
    params: dict[str, Any] = {
        "fields": "id,name,status,objective,date_start,date_end,budget_limit,budget_limit_day",
        "limit": limit,
        "sorting": "-id",
    }
    if not include_deleted:
        params["_status__ne"] = "deleted"

    data = api_get("/ad_plans.json", access, params=params, auto_refresh=False)
    raw_items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(raw_items, list):
        raw_items = []

    campaigns = [_normalize_plan(x) for x in raw_items if isinstance(x, dict)]
    active = sum(1 for c in campaigns if c["status"] == "active")
    blocked = sum(1 for c in campaigns if c["status"] == "blocked")
    day_budgets = [c["budget_limit_day"] for c in campaigns if c["budget_limit_day"] is not None]
    total_day = round(sum(day_budgets), 2) if day_budgets else None

    warnings: list[str] = []
    if not campaigns:
        warnings.append(
            "Кампаний не найдено. Если в кабинете ads.vk.com они есть — "
            "проверьте, что токен выдан именно для этого кабинета."
        )

    return {
        "campaigns": campaigns,
        "count": len(campaigns),
        "active_count": active,
        "blocked_count": blocked,
        "total_day_budget": total_day,
        "warnings": warnings,
        "source": "vk_ads_v2",
        "cabinet_url": "https://ads.vk.com/",
        "access_token": access,
    }
