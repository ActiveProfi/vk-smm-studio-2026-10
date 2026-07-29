"""Веб-поиск материалов по теме (лёгкий поиск без отдельных платных ключей)."""
from __future__ import annotations

import json
import re
from html import unescape
from urllib import parse, request

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0 Safari/537.36"
)


def _fetch(url: str, timeout: int = 20) -> str:
    req = request.Request(url, headers={"User-Agent": USER_AGENT})
    with request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def search_topic(topic: str, *, max_results: int = 5, search_hint: str = "") -> list[dict]:
    """
    Ищет материалы по теме через DuckDuckGo HTML.
    search_hint — уточнение тематики канала (например «НДС 2026 ФНС» или «SMM ВКонтакте»).
    Возвращает список {title, url, snippet}.
    """
    query = topic.strip()
    if not query:
        return []

    hint = (search_hint or "").strip()
    if hint:
        full_query = f"{query} {hint}"
    else:
        full_query = query
    url = "https://html.duckduckgo.com/html/?" + parse.urlencode({"q": full_query})

    try:
        html = _fetch(url)
    except Exception as exc:  # noqa: BLE001
        return [{"title": "Ошибка поиска", "url": "", "snippet": str(exc)}]

    results: list[dict] = []
    # Результаты DuckDuckGo HTML: блоки result__a и result__snippet
    link_pattern = re.compile(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    snippet_pattern = re.compile(
        r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)>',
        re.IGNORECASE | re.DOTALL,
    )

    links = link_pattern.findall(html)
    snippets = snippet_pattern.findall(html)

    for i, (href, title_html) in enumerate(links[:max_results]):
        title = re.sub(r"<[^>]+>", "", unescape(title_html)).strip()
        snippet = ""
        if i < len(snippets):
            snippet = re.sub(r"<[^>]+>", "", unescape(snippets[i])).strip()
        # DuckDuckGo иногда оборачивает ссылку в redirect
        real_url = href
        if "uddg=" in href:
            parsed = parse.parse_qs(parse.urlparse(href).query)
            real_url = parse.unquote(parsed.get("uddg", [href])[0])
        results.append({"title": title, "url": real_url, "snippet": snippet})

    return results


def format_search_for_agent(results: list[dict]) -> str:
    if not results:
        return "Веб-поиск не вернул результатов."
    lines = ["Результаты веб-поиска по теме:"]
    for i, item in enumerate(results, 1):
        lines.append(f"{i}. {item.get('title', '')}")
        if item.get("url"):
            lines.append(f"   URL: {item['url']}")
        if item.get("snippet"):
            lines.append(f"   Фрагмент: {item['snippet']}")
    return "\n".join(lines)


def search_notes_json(results: list[dict]) -> str:
    return json.dumps(results, ensure_ascii=False, indent=2)
