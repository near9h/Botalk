"""Resolve a bot's enabled skills into prompt context + OpenAI tool schemas.

`chat.py` loads the enabled `bot_skills` rows and passes each as a plain dict
(`{"type", "manifest", "config"}`) into the orchestrator. This module turns
those dicts into the two things the LLM call needs:

  * `build_system_context` — knowledge-type instructions + template assets,
    appended to the bot's system prompt.
  * `build_tool_schemas` — OpenAI `tools` parameter entries for `tool` and
    `mcp` skills.
  * `run_tool_call` — dispatch a single tool call to a built-in handler or an
    external MCP server, returning a string result.
  * `ensure_tools_cached` — for lazy MCP skills (e.g. MCP-Marketplace), fetch
    and cache the live `list_tools()` result into the manifest before we
    hand the skill to the LLM.
"""
from __future__ import annotations

import re
from typing import Any

from app.services import mcp as mcp_service
from app.skills.registry import LAZY_MCP_KEYS
from app.tools import execute_tool

# Tools implemented in-process. Anything outside this set is treated as an
# MCP-remote tool and routed via the MCP client.
_BUILTIN_TOOL_NAMES = {"web_search", "web_crawl", "generate_chart", "generate_document"}

# In-process cache so we only call list_tools() once per process per MCP URL.
_TOOL_CACHE: dict[str, list[dict[str, Any]]] = {}


async def ensure_tools_cached(skill: dict[str, Any], key: str | None = None) -> None:
    """Populate `skill["manifest"]["tools"]` for lazy MCP skills.

    Modifies the dict in place. Safe to call repeatedly; only one network
    round-trip per (key, url) pair per process.
    """
    if skill.get("type") != "mcp":
        return
    if key is None or key not in LAZY_MCP_KEYS:
        return
    manifest = skill.get("manifest") or {}
    if manifest.get("tools"):
        return  # already populated (e.g. user re-imported with a cache)
    url = manifest.get("url") or ""
    transport = manifest.get("transport") or "streamable-http"
    cache_key = f"{transport}:{url}"
    if cache_key not in _TOOL_CACHE:
        try:
            _TOOL_CACHE[cache_key] = await mcp_service.list_tools(url, transport)
        except Exception:
            # Network outage / wrong URL — leave empty so the LLM has no
            # tools to call from this skill rather than throwing per turn.
            _TOOL_CACHE[cache_key] = []
    tools = _TOOL_CACHE[cache_key]
    new_manifest = dict(manifest)
    new_manifest["tools"] = tools
    skill["manifest"] = new_manifest


def _normalize_assets(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Backfill id/description/is_default onto legacy asset rows.

    Older assets only carried `{name, content_md}`. Normalize them so the
    template-selection logic below can treat every row uniformly without
    branching on missing keys.
    """
    out: list[dict[str, Any]] = []
    for i, a in enumerate(assets or []):
        out.append(
            {
                "id": a.get("id") or f"asset-{i}",
                "name": a.get("name") or f"模板{i + 1}",
                "description": a.get("description") or "",
                "content_md": a.get("content_md") or "",
                "is_default": bool(a.get("is_default")),
            }
        )
    return out


def _pick_template(
    assets: list[dict[str, Any]], user_prompt: str | None
) -> dict[str, Any] | None:
    """Pick which template's full body to inject.

    Priority:
      1. A template whose name appears verbatim in the user's message
         (e.g. "用周报模板" → the "周报模板" template). Names are compared
         whitespace-insensitively and only for names ≥ 2 chars to avoid
         spurious single-char matches.
      2. The asset flagged `is_default`.
      3. The first asset (so a skill with templates always resolves to one).
    """
    if not assets:
        return None

    if user_prompt:
        norm_prompt = re.sub(r"\s+", "", user_prompt.lower())
        for a in assets:
            name = a.get("name") or ""
            norm_name = re.sub(r"\s+", "", name.lower())
            if len(norm_name) >= 2 and norm_name in norm_prompt:
                return a

    for a in assets:
        if a.get("is_default"):
            return a

    return assets[0]


def build_system_context(
    skills: list[dict[str, Any]], user_prompt: str | None = None
) -> str:
    """Build knowledge-skill context (instructions + template assets).

    For multi-template skills we no longer inline every template's full body
    (which bloated the prompt and made models mix up structures). Instead:

      * The chosen template's full body is inlined (user-named → default →
        first).
      * All other templates only appear as a short "catalog" line
        (`name — description`) so the model knows it can switch by name.

    `user_prompt` is the current user question, used to detect an explicit
    template name mention.
    """
    parts: list[str] = []
    for s in skills:
        if s.get("type") != "knowledge":
            continue
        manifest = s.get("manifest") or {}
        instructions = (manifest.get("instructions") or "").strip()
        if instructions:
            parts.append(instructions)

        assets = _normalize_assets(manifest.get("assets") or [])
        if not assets:
            continue

        chosen = _pick_template(assets, user_prompt)

        # Catalog lets the model see all options without paying the token
        # cost of every template's full body.
        catalog_lines = [
            f"- {a['name']}：{a.get('description') or '无描述'}"
            + ("（默认）" if a.get("is_default") else "")
            for a in assets
        ]
        parts.append(
            "【可用模板清单】（默认使用当前模板，如需切换请明确写出目标模板名）\n"
            + "\n".join(catalog_lines)
        )

        if chosen:
            body = (chosen.get("content_md") or "").strip()
            if body:
                parts.append(f"【当前模板：{chosen['name']}】\n{body}")
    return "\n\n".join(parts)


def build_tool_schemas(skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collect OpenAI tool schemas from tool + mcp skills."""
    out: list[dict[str, Any]] = []
    for s in skills:
        if s.get("type") == "tool":
            out.extend((s.get("manifest") or {}).get("tools") or [])
        elif s.get("type") == "mcp":
            tools = (s.get("manifest") or {}).get("tools") or []
            out.extend(mcp_service.mcp_tools_to_openai(tools))
    return out


async def run_tool_call(
    skills: list[dict[str, Any]], name: str, arguments: dict[str, Any]
) -> str:
    """Execute a tool by name, routing to built-in handlers or MCP servers."""
    # Built-in tools read their API-key config from the first tool skill's
    # per-bot `config` (which falls back to global settings in the handlers).
    if name in _BUILTIN_TOOL_NAMES:
        config: dict[str, Any] = {}
        # For tool skills, prefer the config of whichever enabled skill
        # # actually owns this tool. For built-in tools we just pick the
        # # first available tool-skill config and let the handler fall back
        # # to global env settings when it needs an API key.
        for s in skills:
            if s.get("type") == "tool":
                config = s.get("config") or {}
                break
        return await execute_tool(name, arguments, config)

    for s in skills:
        if s.get("type") != "mcp":
            continue
        manifest = s.get("manifest") or {}
        tool_names = {t.get("name") for t in (manifest.get("tools") or [])}
        if name in tool_names:
            return await mcp_service.call_tool(
                manifest.get("url", ""),
                manifest.get("transport") or "streamable-http",
                name,
                arguments or {},
            )

    return f"[工具错误] 未找到工具: {name}"