"""Web search tool — Tavily → Serper → DuckDuckGo HTML fallback."""
from __future__ import annotations

import html as html_lib
import re

import httpx

from app.config import get_settings

settings = get_settings()

_STRIP_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    text = _STRIP_TAG_RE.sub("", text or "")
    return html_lib.unescape(text).strip()


async def web_search(args: dict, config: dict | None = None) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return "[工具错误] web_search 缺少 query 参数"
    max_results = int(args.get("max_results") or 5)

    cfg = config or {}
    tavily_key = cfg.get("tavily_api_key") or settings.tavily_api_key
    if tavily_key:
        result = await _tavily(query, tavily_key, max_results)
        if result:
            return result

    serper_key = cfg.get("serper_api_key") or settings.serper_api_key
    if serper_key:
        result = await _serper(query, serper_key, max_results)
        if result:
            return result

    return await _duckduckgo(query, max_results)


async def _tavily(query: str, key: str, max_results: int) -> str:
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": key,
                    "query": query,
                    "max_results": max_results,
                    "include_answer": True,
                },
            )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return ""

    lines: list[str] = []
    if data.get("answer"):
        lines.append(f"**摘要**：{data['answer']}")
        lines.append("")
    for r in data.get("results", [])[:max_results]:
        title = _clean(r.get("title", ""))
        url = r.get("url", "")
        content = _clean(r.get("content", ""))[:300]
        lines.append(f"- [{title}]({url})")
        lines.append(f"  {content}")
    return "\n".join(lines) if lines else ""


async def _serper(query: str, key: str, max_results: int) -> str:
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": key, "Content-Type": "application/json"},
                json={"q": query, "num": max_results},
            )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return ""

    lines: list[str] = []
    for r in data.get("organic", [])[:max_results]:
        title = _clean(r.get("title", ""))
        link = r.get("link", "")
        snippet = _clean(r.get("snippet", ""))[:300]
        lines.append(f"- [{title}]({link})")
        lines.append(f"  {snippet}")
    return "\n".join(lines) if lines else ""


async def _duckduckgo(query: str, max_results: int) -> str:
    """Free fallback: scrape DuckDuckGo HTML results (no API key needed)."""
    try:
        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
        ) as client:
            resp = await client.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
            )
        resp.raise_for_status()
        text = resp.text
    except Exception as exc:
        return f"[工具错误] 搜索失败: {exc}"

    results: list[str] = []
    # Each result is wrapped in <a class="result__a" href="…">title</a> plus a
    # <a class="result__snippet" …>snippet</a>. Parse both with a light regex.
    links = re.findall(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        text,
        re.S,
    )
    snippets = re.findall(
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        text,
        re.S,
    )
    for i, (href, title) in enumerate(links[:max_results]):
        title = _clean(title)
        snippet = _clean(snippets[i]) if i < len(snippets) else ""
        # DuckDuckGo wraps real URLs in its own redirect; keep the value as-is.
        results.append(f"- [{title}]({href})")
        if snippet:
            results.append(f"  {snippet[:300]}")
    return "\n".join(results) if results else "[工具错误] 未获取到搜索结果"
