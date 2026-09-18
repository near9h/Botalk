"""Built-in skill definitions + idempotent startup seeding.

Built-in skills are the single source of truth for the capabilities the
skill center ships out of the box: document writer (knowledge), web search,
web crawl, chart generation, document generation (tool) and the
MCP-Marketplace community search (MCP). `ensure_builtin_skills` upserts by
`key` at app startup so code edits win over any stale DB rows.

The MCP-Marketplace skill lazily lists its tools on first resolve so we
don't hit the network during app startup.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Skill

_BUILTIN_SKILLS: list[dict] = [
    {
        "key": "document_writer",
        "name": "写文档",
        "description": (
            "按上传的 Markdown 文档模板生成结构化文档、测试报告、纪要等；"
            "通过结构化 JSON 输出 + 模板引擎渲染产出 HTML 与 docx，保证"
            "「同一 prompt → 同一文件」的稳定性。"
        ),
        "type": "knowledge",
        "category": "document",
        "icon": "📝",
        "config_schema": {
            "assets": {
                "type": "list",
                "label": "文档模板（仅 Markdown）",
                "accept": [".md", ".txt"],
                "hint": (
                    "只支持 .md / .txt。Markdown 的标题层级、表格、列表会保留下来，"
                    "AI 会严格按模板的章节结构与字段填充正文。"
                ),
            }
        },
        "manifest": {
            # 路线 B 指令：让模型把整条回复当作 JSON 对象返回。
            # 真正的 schema 文本由 msghub 在拼 system prompt 时注入。
            "instructions": (
                "你具备「写文档」能力。当用户要求撰写文档、报告、测试报告、"
                "纪要、需求文档等时：\n"
                "1) 你已配置若干 Markdown 文档模板（清单会附在 system prompt 里）。"
                " 严格按当前模板的章节顺序与字段结构填充；\n"
                "2) **整条回复必须且只能是一个 JSON 对象**（不要写 markdown 文本、"
                "不要写列表、不要包裹在 ``` 里）。JSON 结构（详见上方 [文档结构] 段）：\n"
                "   - title: 报告主题\n"
                "   - summary: 一段执行摘要\n"
                "   - sections: 至少 2 个章节，每节 body 用 Markdown 写正文\n"
                "   - tags / language 可选\n"
                "3) 后端会把这份 JSON 渲染成 HTML 与 docx 并自动生成下载链接；"
                "你不需要（也不应该）调用任何工具来「保存」文档；\n"
                "4) 涉及数据或事实时给出依据；\n"
                "5) 使用与用户一致的语言。\n\n"
                "如果系统 prompt 里没有出现 [文档结构] 段（说明路由到的是旧版"
                "工具链），则退回旧约定：完整 Markdown 用 ``` 包裹，并调用 "
                "generate_document(markdown=..., filename=..., title=...) 工具。"
            ),
            "assets": [],
            # 标记位：msghub 据此决定是否注入 schema 文本 + 拦截 tool_calls。
            "structured_output": True,
        },
    },
    {
        "key": "web_search",
        "name": "网页搜索",
        "description": "联网搜索外部数据并用于分析，返回带来源链接的结果。",
        "type": "tool",
        "category": "search",
        "icon": "🔎",
        "config_schema": {
            "fields": [
                {
                    "key": "tavily_api_key",
                    "label": "Tavily API Key（可选）",
                    "secret": True,
                    "hint": "配置后优先用 Tavily，未配置则用 Serper 或直接抓取兜底",
                },
                {
                    "key": "serper_api_key",
                    "label": "Serper API Key（可选）",
                    "secret": True,
                },
            ]
        },
        "manifest": {
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "description": "联网搜索最新信息，返回带标题、链接、摘要的结果列表。",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "搜索关键词或问题",
                                },
                                "max_results": {
                                    "type": "integer",
                                    "description": "期望返回的结果条数",
                                },
                            },
                            "required": ["query"],
                        },
                    },
                }
            ]
        },
    },
    {
        "key": "web_crawl",
        "name": "网页爬取",
        "description": "抓取指定网址的正文与明细内容，转成 Markdown 供分析。",
        "type": "tool",
        "category": "crawl",
        "icon": "🕸️",
        "config_schema": {
            "fields": [
                {
                    "key": "firecrawl_api_key",
                    "label": "Firecrawl API Key（可选）",
                    "secret": True,
                    "hint": "配置后优先用 Firecrawl 抓取，未配置则用 httpx 直接抓取兜底",
                }
            ]
        },
        "manifest": {
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "web_crawl",
                        "description": "抓取指定 URL 的网页正文，返回 Markdown 格式内容。",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "url": {
                                    "type": "string",
                                    "description": "要抓取的网页 URL",
                                }
                            },
                            "required": ["url"],
                        },
                    },
                }
            ]
        },
    },
    {
        "key": "chart",
        "name": "图表生成",
        "description": "根据数据生成 ECharts 图表 HTML，供回答中可视化展示。",
        "type": "tool",
        "category": "chart",
        "icon": "📊",
        "config_schema": {},
        "manifest": {
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "generate_chart",
                        "description": (
                            "把结构化数据生成一个 ECharts 图表。spec 需包含 chartType"
                            "（bar/line/pie/scatter）、title、labels（类目数组）和 series"
                            "（每项含 name 与 data 数组）。"
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "spec": {
                                    "type": "object",
                                    "description": "图表配置：{chartType, title, labels[], series[{name, data[]}]}",
                                }
                            },
                            "required": ["spec"],
                        },
                    },
                }
            ]
        },
    },
    {
        "key": "generate_document",
        "name": "文档生成",
        "description": (
            "把 LLM 产出的 Markdown 一键转成 Word (.docx) 文档，含目录；"
            "下载链接会在聊天中以「📄 文档已生成」卡片呈现。"
        ),
        "type": "tool",
        "category": "document",
        "icon": "📄",
        "config_schema": {},
        "manifest": {
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "generate_document",
                        "description": (
                            "把 Markdown 内容转成 Word (.docx) 文件，自动生成目录。"
                            "返回的字符串里包含 `[下载](attachment://<id>)` 链接，"
                            "前端会渲染为下载卡片。"
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "markdown": {
                                    "type": "string",
                                    "description": "完整的 Markdown 正文（标题/章节/表格/列表 完整保留）。",
                                },
                                "filename": {
                                    "type": "string",
                                    "description": "下载文件名，可不含后缀（默认会自动补 .docx）。",
                                },
                                "title": {
                                    "type": "string",
                                    "description": "文档主题的一句话摘要，会显示在气泡里。",
                                },
                            },
                            "required": ["markdown"],
                        },
                    },
                }
            ]
        },
    },
    {
        "key": "mcp_marketplace",
        "name": "MCP 技能市场",
        "description": (
            "从 MCP Marketplace (mcp-marketplace.io) 搜索/查询可接入的 MCP server，"
            "由 LLM 在讨论中按需调用。"
        ),
        "type": "mcp",
        "category": "mcp",
        "icon": "🛒",
        "config_schema": {},
        "manifest": {
            "url": "https://mcp-marketplace.io/api/mcp/mcp",
            "transport": "streamable-http",
            # 留空，运行时由 resolve.ensure_tools_cached 调 list_tools 填充
            "tools": [],
        },
    },
]


# Built-in MCP skills whose `manifest.tools` should be (re)populated lazily
# by `ensure_tools_cached` because listing tools requires a live network call.
LAZY_MCP_KEYS = {"mcp_marketplace"}


async def ensure_builtin_skills(session: AsyncSession) -> None:
    """Upsert built-in skills by key (idempotent; safe to call every boot)."""
    for spec in _BUILTIN_SKILLS:
        result = await session.execute(
            select(Skill).where(Skill.key == spec["key"])
        )
        row = result.scalar_one_or_none()
        if row is None:
            session.add(Skill(**spec, builtin=True))
        else:
            # Keep code as the source of truth for manifest/schema/metadata.
            row.name = spec["name"]
            row.description = spec["description"]
            row.type = spec["type"]
            row.category = spec["category"]
            row.icon = spec["icon"]
            row.config_schema = spec["config_schema"]
            # Preserve user-uploaded template assets when refreshing the writer.
            if spec["key"] != "document_writer":
                row.manifest = spec["manifest"]
            else:
                merged = dict(spec["manifest"])
                merged["assets"] = (row.manifest or {}).get("assets", [])
                row.manifest = merged
    await session.commit()


async def get_builtin_skill(session: AsyncSession, key: str) -> Skill | None:
    """Fetch a built-in skill row by key."""
    result = await session.execute(select(Skill).where(Skill.key == key))
    return result.scalar_one_or_none()