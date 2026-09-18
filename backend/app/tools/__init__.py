"""Built-in skill tools + dispatcher.

Each tool is an async function `handler(args: dict, config: dict) -> str`
returning a Markdown/HTML string. The dispatcher catches all errors and
returns them as text so a tool failure never crashes the discussion loop --
the LLM sees the error and can adapt.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from app.tools import chart, crawl, document, search

ToolHandler = Callable[[dict[str, Any], dict[str, Any]], Awaitable[str]]

TOOL_HANDLERS: dict[str, ToolHandler] = {
    "web_search": search.web_search,
    "web_crawl": crawl.web_crawl,
    "generate_chart": chart.generate_chart,
    "generate_document": document.generate_document,
}


async def execute_tool(name: str, args: dict[str, Any], config: dict[str, Any] | None = None) -> str:
    """Run a tool by name, returning its result string (never raising)."""
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return f"[工具错误] 未注册的工具: {name}"
    try:
        return await handler(args or {}, config or {})
    except Exception as exc:  # noqa: BLE001
        return f"[工具错误] {name} 执行失败: {exc}"