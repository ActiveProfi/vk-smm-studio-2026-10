"""Портфель кабинетов VK Реклама и сводные отчёты по каналам."""
from __future__ import annotations

from datetime import datetime, timedelta

from webapp.models import Workspace
from webapp.services import access as acc
from webapp.services import vk_ads_client


ADS_PLANS = {"pro", "agency", "free"}  # free = триал для теста


def plan_includes_ads(user) -> bool:
    code = (getattr(user, "plan_code", None) or "free").strip().lower()
    status = (getattr(user, "plan_status", None) or "").strip().lower()
    if code in {"pro", "agency"}:
        return True
    if code == "free" or status in {"trial", "test_paid"}:
        return True
    return False


def suggested_channel_limit(user) -> int:
    """Мягкий ориентир лимита каналов по тарифу (пока без жёсткой блокировки оплаты)."""
    code = (getattr(user, "plan_code", None) or "free").strip().lower()
    note = (getattr(user, "plan_channels_note", None) or "").strip()
    # пример note: «3×business»
    if "×" in note:
        try:
            return max(1, min(100, int(note.split("×", 1)[0])))
        except ValueError:
            pass
    return {"free": 3, "standard": 10, "pro": 20, "agency": 50}.get(code, 10)


def cabinet_row(ws: Workspace) -> dict:
    status = (ws.vk_ads_status or "").strip()
    has_creds = bool((ws.vk_ads_client_id or "").strip() and (ws.vk_ads_client_secret or "").strip())
    has_token = bool((ws.vk_ads_token or "").strip())
    if not status:
        if has_token or has_creds:
            status = "connected" if has_token else "pending"
        else:
            status = "empty"
    status_label = {
        "connected": "Подключено",
        "error": "Ошибка",
        "pending": "Данные есть, нужен вход",
        "empty": "Не подключено",
    }.get(status, status)
    return {
        "workspace_id": ws.id,
        "channel_name": ws.name or f"Канал {ws.id}",
        "account_id": (ws.vk_ads_account_id or "").strip(),
        "client_id": (ws.vk_ads_client_id or "").strip(),
        "has_secret": bool((ws.vk_ads_client_secret or "").strip()),
        "has_token": has_token,
        "status": status,
        "status_label": status_label,
        "last_error": (ws.vk_ads_last_error or "").strip(),
        "connected_at": (ws.vk_ads_connected_at or "").strip(),
        "cabinet_url": vk_ads_client.cabinet_url(),
    }


def list_cabinets(user) -> list[dict]:
    rows = []
    for ws in acc.list_workspaces(user, active_only=True):
        rows.append(cabinet_row(ws))
    return rows


def connect_workspace(
    ws: Workspace,
    *,
    client_id: str,
    client_secret: str,
    account_id: str = "",
) -> dict:
    """Сохранить credentials и получить токены VK Ads для канала."""
    client_id = (client_id or "").strip()
    client_secret = (client_secret or "").strip()
    account_id = (account_id or "").strip()
    if not client_id or not client_secret:
        raise ValueError("Укажите Client ID и Client Secret из ads.vk.ru → Доступ к API.")

    tokens = vk_ads_client.obtain_tokens_raw(client_id, client_secret)
    from webapp.services.secrets_box import seal

    ws.vk_ads_client_id = client_id
    ws.vk_ads_client_secret = seal(client_secret)
    if account_id:
        ws.vk_ads_account_id = account_id
    ws.vk_ads_token = seal(tokens["access_token"])
    ws.vk_ads_refresh_token = seal(tokens.get("refresh_token") or "")
    ws.vk_ads_token_expires_at = tokens.get("expires_at") or ""
    ws.vk_ads_status = "connected"
    ws.vk_ads_last_error = ""
    ws.vk_ads_connected_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    # быстрая проверка
    check = vk_ads_client.test_connection(token=tokens["access_token"])
    return {
        "ok": True,
        "message": check.get("message") or "Кабинет подключён.",
        "sample_count": check.get("sample_count", 0),
    }


def ensure_ws_token(ws: Workspace) -> str:
    return vk_ads_client.ensure_workspace_access_token(ws)


def default_period(days: int = 7) -> tuple[str, str]:
    end = datetime.utcnow().date()
    start = end - timedelta(days=max(1, days) - 1)
    return start.isoformat(), end.isoformat()


def build_ads_report(user, workspace_ids: list[int], date_from: str, date_to: str) -> dict:
    """Сводка по выбранным каналам за период."""
    allowed = {w.id: w for w in acc.list_workspaces(user, active_only=False)}
    selected: list[Workspace] = []
    for wid in workspace_ids:
        ws = allowed.get(int(wid))
        if ws:
            selected.append(ws)

    channels = []
    total_spent = 0.0
    total_shows = 0
    total_clicks = 0
    warnings: list[str] = []

    for ws in selected:
        row = {
            "workspace_id": ws.id,
            "channel_name": ws.name,
            "account_id": (ws.vk_ads_account_id or "").strip(),
            "status": (ws.vk_ads_status or "").strip() or "empty",
            "spent": None,
            "shows": None,
            "clicks": None,
            "ctr": None,
            "error": "",
            "campaigns": 0,
        }
        if not (ws.vk_ads_token or "").strip() and not (
            (ws.vk_ads_client_id or "").strip() and (ws.vk_ads_client_secret or "").strip()
        ):
            row["error"] = "Кабинет не подключён"
            warnings.append(f"{ws.name}: кабинет не подключён")
            channels.append(row)
            continue
        try:
            token = ensure_ws_token(ws)
            stats = vk_ads_client.get_period_summary(
                token=token,
                date_from=date_from,
                date_to=date_to,
            )
            camps = vk_ads_client.get_campaigns(token=token, limit=50)
            # sync refreshed token
            fresh = camps.get("access_token") or token
            from webapp.services.secrets_box import reveal, seal

            if fresh and fresh != reveal(ws.vk_ads_token):
                ws.vk_ads_token = seal(fresh)
            row["spent"] = stats.get("spent")
            row["shows"] = stats.get("shows")
            row["clicks"] = stats.get("clicks")
            row["ctr"] = stats.get("ctr")
            row["campaigns"] = camps.get("count") or 0
            if stats.get("spent") is not None:
                total_spent += float(stats["spent"])
            if stats.get("shows") is not None:
                total_shows += int(stats["shows"])
            if stats.get("clicks") is not None:
                total_clicks += int(stats["clicks"])
            if stats.get("warning"):
                warnings.append(f"{ws.name}: {stats['warning']}")
        except Exception as exc:  # noqa: BLE001
            row["error"] = str(exc)
            row["status"] = "error"
            ws.vk_ads_status = "error"
            ws.vk_ads_last_error = str(exc)[:500]
            warnings.append(f"{ws.name}: {exc}")
        channels.append(row)

    ctr_total = None
    if total_shows > 0:
        ctr_total = round(100.0 * total_clicks / total_shows, 2)

    return {
        "date_from": date_from,
        "date_to": date_to,
        "channels": channels,
        "selected_count": len(selected),
        "totals": {
            "spent": round(total_spent, 2),
            "shows": total_shows,
            "clicks": total_clicks,
            "ctr": ctr_total,
        },
        "warnings": warnings,
    }
