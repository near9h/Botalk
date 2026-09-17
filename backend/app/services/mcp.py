"""MCP (Model Context Protocol) client wrapper.

Supports remote HTTP-based transports (`streamable-http` and `sse`) so the
skill center can import tools from public MCP servers (LobeHub marketplace,
mcp.so, etc.). `stdio` transport is intentionally out of scope for now.

The `mcp` SDK is imported lazily so the rest of the app still boots if the
dependency is missing in a stripped-down deployment.
"""
from __future__ import annotations

import json
from typing import Any

from app.config import get_settings

settings = get_settings()


def _mcp_sdk():
    try:
        import mcp  # noqa: F401
        from mcp import ClientSession
        from mcp.client.sse import sse_client
        from mcp.client.streamable_http import streamablehttp_client

        return ClientSession, sse_client, streamablehttp_client
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("MCP SDK 未安装，请安装 `mcp` 依赖") from exc


def _client_context(transport: str, url: str):
    ClientSession, sse_client, streamablehttp_client = _mcp_sdk()
    timeout = settings.mcp_timeout_seconds
    if transport == "sse":
        return sse_client(url, timeout=timeout)
    # default + fallback: streamable http
    return streamablehttp_client(url, timeout=timeout)


async def list_tools(url: str, transport: str = "streamable-http") -> list[dict[str, Any]]:
    """Connect to an MCP server and return its tools (normalized)."""
    ClientSession, _, _ = _mcp_sdk()
    out: list[dict[str, Any]] = []
    async with _client_context(transport, url) as streams:
        if len(streams) == 3:
            read, write, _get_session_id = streams
        else:
            read, write = streams
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            for t in result.tools:
                out.append(
                    {
                        "name": t.name,
                        "description": t.description or "",
                        "inputSchema": t.inputSchema or {},
                    }
                )
    return out


async def call_tool(
    url: str, transport: str, tool_name: str, arguments: dict[str, Any]
) -> str:
    """Call an MCP tool and serialize its content blocks to a string."""
    ClientSession, _, _ = _mcp_sdk()
    async with _client_context(transport, url) as streams:
        if len(streams) == 3:
            read, write, _get_session_id = streams
        else:
            read, write = streams
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments or {})
            return _serialize_content(result.content, result.isError)


def _serialize_content(content: Any, is_error: bool) -> str:
    parts: list[str] = []
    if isinstance(content, list):
        for block in content:
            text = getattr(block, "text", None)
            if text is not None:
                parts.append(str(text))
            else:
                raw = getattr(block, "model_dump", None)
                if raw:
                    parts.append(json.dumps(raw(), ensure_ascii=False))
                else:
                    parts.append(str(block))
    else:
        parts.append(str(content))
    body = "\n".join(p for p in parts if p)
    if is_error:
        body = f"[MCP 工具错误]\n{body}"
    return body or "(空结果)"


def mcp_tools_to_openai(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert normalized MCP tools to OpenAI `tools` parameter format."""
    out: list[dict[str, Any]] = []
    for t in tools:
        schema = t.get("inputSchema") or {}
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description") or "",
                    "parameters": _to_json_schema(schema),
                },
            }
        )
    return out


def _to_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """MCP inputSchema is already JSON Schema; strip unsupported keywords."""
    if not schema:
        return {"type": "object", "properties": {}}
    allowed = {"type", "properties", "required", "description", "items", "enum", "default"}
    return {k: v for k, v in schema.items() if k in allowed}
