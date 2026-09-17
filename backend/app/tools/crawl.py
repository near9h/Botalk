"""Web crawl tool — Firecrawl → direct httpx fetch + HTML→Markdown extraction."""
from __future__ import annotations

import re
from html.parser import HTMLParser

import httpx

from app.config import get_settings

settings = get_settings()


async def web_crawl(args: dict, config: dict | None = None) -> str:
    url = str(args.get("url", "")).strip()
    if not url:
        return "[工具错误] web_crawl 缺少 url 参数"
    if not url.startswith(("http://", "https://")):
        return "[工具错误] url 必须以 http:// 或 https:// 开头"

    cfg = config or {}
    firecrawl_key = cfg.get("firecrawl_api_key") or settings.firecrawl_api_key
    if firecrawl_key:
        result = await _firecrawl(url, firecrawl_key)
        if result:
            return result

    return await _direct_fetch(url)


async def _firecrawl(url: str, key: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.firecrawl.dev/v1/scrape",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"url": url, "formats": ["markdown"]},
            )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return ""
    md = (data.get("data") or {}).get("markdown") or ""
    if not md:
        return ""
    return _truncate(md)


async def _direct_fetch(url: str) -> str:
    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
        ) as client:
            resp = await client.get(url)
        resp.raise_for_status()
        html = resp.text
    except Exception as exc:
        return f"[工具错误] 抓取失败: {exc}"

    md = html_to_markdown(html)
    if not md.strip():
        return "[工具错误] 未解析到正文内容"
    return _truncate(md)


def _truncate(md: str, limit: int = 8000) -> str:
    if len(md) > limit:
        return md[:limit] + f"\n\n…(内容已截断，原文共 {len(md)} 字符)"
    return md


class _MarkdownExtractor(HTMLParser):
    """Minimal HTML→Markdown extractor. Keeps headings, paragraphs, lists,
    links, tables (as pipe rows) and code, drops script/style/nav/header."""

    _SKIP_TAGS = {"script", "style", "nav", "header", "footer", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__()
        self.out: list[str] = []
        self._skip_depth = 0
        self._in_pre = False
        self._href: str | None = None
        self._buf: list[str] = []
        self._li_stack: list[str] = []

    def _flush_inline(self) -> str:
        text = "".join(self._buf).strip()
        self._buf = []
        return re.sub(r"\s+", " ", text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        attr = dict(attrs)
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._flush_inline()
            level = int(tag[1])
            self.out.append("\n" + "#" * level + " ")
        elif tag == "p":
            self._flush_inline()
            self.out.append("\n")
        elif tag == "br":
            self._buf.append("\n")
        elif tag == "li":
            self._flush_inline()
            self.out.append("\n- ")
        elif tag == "a":
            self._href = attr.get("href")
        elif tag == "pre":
            self._in_pre = True
            self._flush_inline()
            self.out.append("\n```\n")
        elif tag == "code" and not self._in_pre:
            self._buf.append("`")
        elif tag in ("td", "th"):
            self._flush_inline()
            self.out.append(" | ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "tr"):
            self.out.append("\n")
        elif tag == "a":
            text = self._flush_inline()
            if self._href:
                self.out.append(f"[{text}]({self._href})")
            else:
                self.out.append(text)
            self._href = None
        elif tag == "pre":
            self._in_pre = False
            self.out.append("\n```\n")
        elif tag == "code" and not self._in_pre:
            self._buf.append("`")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_pre:
            self.out.append(data)
        else:
            self._buf.append(data)


def html_to_markdown(html: str) -> str:
    parser = _MarkdownExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass
    text = "".join(parser.out)
    # Collapse excessive blank lines.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
