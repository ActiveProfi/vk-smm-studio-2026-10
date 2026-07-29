"""Корзина материалов для экрана генерации (файлы + веб-поиск) в session."""
from __future__ import annotations

import uuid
from pathlib import Path

from flask import session


SESSION_KEY = "gen_materials_bag"
WORKSPACE_BIND_KEY = "gen_materials_workspace_id"


def bind_workspace(workspace_id: int) -> bool:
    """
    Корзина материалов принадлежит одному каналу.
    При смене канала — полностью очищаем файлы и веб-поиск.
    Возвращает True, если корзина была очищена.
    """
    ws_id = int(workspace_id)
    prev = session.get(WORKSPACE_BIND_KEY)
    raw_bag = session.get(SESSION_KEY)
    has_orphan_bag = (
        prev is None
        and isinstance(raw_bag, dict)
        and (raw_bag.get("files") or raw_bag.get("search"))
    )

    if prev is not None and int(prev) != ws_id:
        session.pop(SESSION_KEY, None)
        session[WORKSPACE_BIND_KEY] = ws_id
        session.modified = True
        return True
    if has_orphan_bag:
        session.pop(SESSION_KEY, None)
        session[WORKSPACE_BIND_KEY] = ws_id
        session.modified = True
        return True
    if prev is None:
        session[WORKSPACE_BIND_KEY] = ws_id
        session.modified = True
    return False


def _bag() -> dict:
    data = session.get(SESSION_KEY)
    if not isinstance(data, dict):
        data = {"files": [], "search": [], "footer_text": "", "footer_files": []}
        session[SESSION_KEY] = data
    data.setdefault("files", [])
    data.setdefault("search", [])
    data.setdefault("footer_text", "")
    data.setdefault("footer_files", [])
    return data


def get_bag() -> dict:
    return _bag()


def clear_bag() -> None:
    session.pop(SESSION_KEY, None)
    session.modified = True


def set_footer_text(text: str) -> str:
    bag = _bag()
    bag["footer_text"] = (text or "").strip()
    session[SESSION_KEY] = bag
    session.modified = True
    return bag["footer_text"]


def get_footer_text() -> str:
    return (_bag().get("footer_text") or "").strip()


def add_footer_file(*, name: str, path: str) -> dict:
    bag = _bag()
    item = {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "path": path,
    }
    bag["footer_files"].append(item)
    session[SESSION_KEY] = bag
    session.modified = True
    return item


def remove_footer_file(file_id: str) -> bool:
    bag = _bag()
    before = len(bag["footer_files"])
    bag["footer_files"] = [f for f in bag["footer_files"] if f.get("id") != file_id]
    session[SESSION_KEY] = bag
    session.modified = True
    return len(bag["footer_files"]) < before


def add_file(*, name: str, path: str, text: str) -> dict:
    bag = _bag()
    item = {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "path": path,
        "chars": len(text),
        "preview": (text[:240] + "…") if len(text) > 240 else text,
    }
    bag["files"].append(item)
    session[SESSION_KEY] = bag
    session.modified = True
    return item


def remove_file(file_id: str) -> bool:
    bag = _bag()
    before = len(bag["files"])
    bag["files"] = [f for f in bag["files"] if f.get("id") != file_id]
    session[SESSION_KEY] = bag
    session.modified = True
    return len(bag["files"]) < before


def add_search_results(results: list[dict]) -> list[dict]:
    bag = _bag()
    added = []
    existing_urls = {s.get("url") for s in bag["search"]}
    for r in results:
        url = (r.get("url") or "").strip()
        if url and url in existing_urls:
            continue
        item = {
            "id": uuid.uuid4().hex[:12],
            "title": (r.get("title") or "Без названия").strip(),
            "url": url,
            "snippet": (r.get("snippet") or "").strip(),
        }
        bag["search"].append(item)
        added.append(item)
        if url:
            existing_urls.add(url)
    session[SESSION_KEY] = bag
    session.modified = True
    return added


def remove_search(item_id: str) -> bool:
    bag = _bag()
    before = len(bag["search"])
    bag["search"] = [s for s in bag["search"] if s.get("id") != item_id]
    session[SESSION_KEY] = bag
    session.modified = True
    return len(bag["search"]) < before


def read_file_text(path_str: str) -> str:
    from webapp.services.extract_text import read_cached_or_extract

    path = Path(path_str)
    if not path.exists():
        return ""
    return read_cached_or_extract(path)


def build_summary(*, topic: str = "") -> str:
    """Саммари-текст из всех загруженных файлов и результатов веб-поиска."""
    bag = _bag()
    parts: list[str] = []
    if topic.strip():
        parts.append(f"Тема: {topic.strip()}")

    if bag["files"]:
        parts.append("=== Загруженные материалы ===")
        for i, f in enumerate(bag["files"], 1):
            text = read_file_text(f.get("path", ""))
            parts.append(f"\n--- Файл {i}: {f.get('name', 'без имени')} ---\n")
            parts.append(text or "(файл пуст или не прочитан)")

    if bag["search"]:
        parts.append("\n=== Материалы из веб-поиска ===")
        for i, s in enumerate(bag["search"], 1):
            parts.append(f"\n{i}. {s.get('title', '')}")
            if s.get("url"):
                parts.append(f"   URL: {s['url']}")
            if s.get("snippet"):
                parts.append(f"   Фрагмент: {s['snippet']}")

    footer_text = (bag.get("footer_text") or "").strip()
    footer_files = bag.get("footer_files") or []
    if footer_text or footer_files:
        parts.append("\n=== Подпись внизу визуала ===")
        if footer_text:
            parts.append(f"Текст подписи: {footer_text}")
            parts.append(
                "В image/video промпте добавь эту подпись маленьким текстом строго по центру в самом низу."
            )
        if footer_files:
            parts.append("Файлы-образцы подписи/логотипа (ориентир для низа кадра):")
            for i, f in enumerate(footer_files, 1):
                parts.append(f"{i}. {f.get('name', 'файл')}")

    summary = "\n".join(parts).strip()
    if len(summary) > 19000:
        summary = summary[:19000] + "\n\n…(саммари обрезано по длине)"
    return summary
