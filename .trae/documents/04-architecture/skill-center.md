# 技能中心（Skill Center）实现计划

## 1. Summary（目标）

为 BotGroup 新增「技能中心」菜单，实现可复用的 AI 技能体系：管理员在技能中心导入/配置技能，在机器人编辑页给不同机器人勾选启用；机器人回答时可通过 **OpenAI function-calling 自动调用** 技能（搜索、爬取、生成图表），也支持用户在群聊中 **手动 `/技能名` 触发**。首期全量交付：

1. **写文档技能**：上传各类文档模板（docx/md/txt），机器人测试完成后按模板输出测试报告等文档。
2. **网页搜索技能**：配置第三方 API（Tavily/Serper）后获取外部数据并分析；未配置时用 httpx 抓取兜底。
3. **网页爬取技能**：给定网址抓取正文/明细内容；配置 Firecrawl 时优先用其 API，否则 httpx 兜底。
4. **图表技能**：AI 回答时生成 ECharts HTML，前端安全渲染图表。
5. **社区对接**：支持导入 **Agent Skills（SKILL.md）** 与 **MCP server**，并可搜索外部技能市场（可配置 registry）。

## 2. 当前状态分析（基于代码走查）

技术栈：FastAPI + SQLAlchemy 2.x(async) + Alembic + PostgreSQL 16；前端 Next.js 14 App Router；后端通过 `openai` SDK 直连 NewAPI（OpenAI 兼容网关）。

关键现状：

- **编排引擎** [msghub.py](file:///root/Documents/trae_projects/botgroup/backend/app/orchestrator/msghub.py)：`_generate_agent()` 目前是**同步、单次、无 tools 参数**的 `chat.completions.create()` 调用；`run_group_discussion()` 按 round 调度发言，末尾有一个固定「📋 总结」pass。
- **机器人模型** [models.py](file:///root/Documents/trae_projects/botgroup/backend/app/db/models.py)：`Bot` 有 `params`(JSON) 字段可直接复用；`Bot` 无技能关联。
- **路由注册** [main.py](file:///root/Documents/trae_projects/botgroup/backend/app/main.py)：已有 `bots/groups/messages/chat/models/attachments/auth` 路由，按前缀 `/api/*` 挂载。
- **Schema** [schemas.py](file:///root/Documents/trae_projects/botgroup/backend/app/schemas.py)：`BotUpdate` 已有，可扩展技能字段。
- **配置** [config.py](file:///root/Documents/trae_projects/botgroup/backend/app/config.py)：`pydantic-settings`，已有 `newapi_*`、`mineru_*` 等，可加搜索/爬取/MCP 相关 key。
- **种子模式**：系统 bot 用迁移 [0005_system_bot.py](file:///root/Documents/trae_projects/botgroup/backend/alembic/versions/0005_system_bot.py) 种子；bootstrap user 用 [auth.py](file:///root/Documents/trae_projects/botgroup/backend/app/auth.py) 在 lifespan 里幂等 seed。
- **前端导航** [Sidebar.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/Sidebar.tsx)：`NAV_KEYS` 数组控制菜单。
- **前端 UI 原语** [ui.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/ui.tsx)：已有 `Dialog/Select/Tabs/Badge/Button/Card/Toast` 等零依赖组件。
- **API 客户端** [api.ts](file:///root/Documents/trae_projects/botgroup/frontend/lib/api.ts)：集中定义类型与 `request()` 封装。
- **Markdown 渲染** [markdown.ts](file:///root/Documents/trae_projects/botgroup/frontend/lib/markdown.ts)：`html:false`，**不渲染原始 HTML**——图表 HTML 必须走专用安全渲染通道（见 3.6）。
- **i18n** [i18n.tsx](file:///root/Documents/trae_projects/botgroup/frontend/lib/i18n.tsx)：中/英字典，需补 `nav.skills` 等词条。

## 3. 方案设计（成熟方案结论）

调研确认两条成熟开放标准，本方案同时支持，作为技能的两种「形态」：

- **Agent Skills（SKILL.md）**：Anthropic 2025 年开源标准，一个文件夹含 `SKILL.md`（YAML frontmatter `name`/`description` + Markdown 指令）及可选 `assets/`（模板）、`scripts/`。已被 32+ 工具采纳。**用于「知识/流程型技能」**（写文档模板）。
- **MCP（Model Context Protocol）**：Anthropic 的开放工具标准，市场有 LobeHub（9.8 万+ server）、mcp.so、skills-hub 等目录。**用于「工具型技能」**（搜索/爬取/图表），也作为「社区对接」入口。

本项目技能统一为一条 `Skill` 记录，用 `type` 区分三种形态：

| type | 含义 | 执行方式 | manifest 内容 |
|---|---|---|---|
| `knowledge` | 知识/流程型（含写文档模板） | 注入 system prompt + assets 作为上下文 | `{instructions, assets:[{name, content_md}]}` |
| `tool` | 内置工具（搜索/爬取/图表） | OpenAI function-calling | `{tools:[{name,description,parameters}]}` |
| `mcp` | 外部 MCP server 工具 | 连 MCP 拉 tools → 转 OpenAI tools → 调用 | `{url, transport, tools:[…cache]}` |

调用机制（用户已确认「两者都要」）：

- **自动**：把机器人已启用技能暴露为 OpenAI `tools` 参数，LLM 自主决定调用；执行结果以 `role:"tool"` 回填，循环直到无 tool_call 或达到 `MAX_TOOL_STEPS`。
- **手动**：解析用户 prompt 中的 `/技能key` 或 `@技能名`，强制先执行对应技能，再继续讨论。

## 4. 具体改动

### 4.1 后端 — 数据模型

**文件** [backend/app/db/models.py](file:///root/Documents/trae_projects/botgroup/backend/app/db/models.py)

新增两个模型：

```python
class Skill(Base):
    __tablename__ = "skills"
    id: int PK
    key: str(64) unique          # 唯一标识，如 web_search / document_writer
    name: str(128)
    description: str Text
    type: str(16)                # knowledge | tool | mcp
    category: str(32)            # document | search | crawl | chart | mcp | custom
    icon: str(8) default "🧩"
    manifest: dict JSON          # type 相关定义（见上表）
    config_schema: dict JSON     # 需要的配置项 schema（用于前端表单，如 api key）
    builtin: bool default False  # 内置技能不可删除
    created_at: datetime

class BotSkill(Base):
    __tablename__ = "bot_skills"
    bot_id FK bots.id CASCADE (PK)
    skill_id FK skills.id CASCADE (PK)
    config: dict JSON default {}  # 机器人级配置覆盖（如自定义模板）
    enabled: bool default True
    created_at: datetime
```

### 4.2 后端 — 迁移

**文件** [backend/alembic/versions/0007_skills.py](file:///root/Documents/trae_projects/botgroup/backend/alembic/versions/0007_skills.py)（新建）

- `op.create_table("skills", …)`、`op.create_table("bot_skills", …)`，含外键与联合主键。
- `down_revision = "0006_widen_mime"`（当前最新迁移）。
- 内置技能**不在迁移里 seed**，改为启动时幂等 seed（见 4.5），理由：manifest/config_schema 为复杂 JSON，代码维护优于 SQL 拼接。

### 4.3 后端 — 配置

**文件** [backend/app/config.py](file:///root/Documents/trae_projects/botgroup/backend/app/config.py) 新增：

```python
tavily_api_key: str = ""
serper_api_key: str = ""
firecrawl_api_key: str = ""
mcp_timeout_seconds: float = 30.0
skill_market_api_url: str = ""   # 社区搜索 registry，空则前端隐藏搜索
```

**文件** [.env.example](file:///root/Documents/trae_projects/botgroup/.env.example) 与 [docker-compose.yml](file:///root/Documents/trae_projects/botgroup/docker-compose.yml)：在 `backend.environment` 透传 `TAVILY_API_KEY/SERPER_API_KEY/FIRECRAWL_API_KEY/SKILL_MARKET_API_URL`。

### 4.4 后端 — 内置技能注册与 seed

**新建** [backend/app/skills/__init__.py](file:///root/Documents/trae_projects/botgroup/backend/app/skills/__init__.py) 与 [backend/app/skills/registry.py](file:///root/Documents/trae_projects/botgroup/backend/app/skills/registry.py)

- `BUILTIN_SKILLS: list[dict]` 定义 4 个内置技能：
  1. `document_writer`（knowledge/category=document）：默认 instructions 说明「严格按模板结构输出文档」；`config_schema` 允许上传模板（`assets`）。
  2. `web_search`（tool/category=search）：tools 含 `web_search(query)`，`config_schema` 声明可配 `TAVILY_API_KEY` / `SERPER_API_KEY`。
  3. `web_crawl`（tool/category=crawl）：tools 含 `web_crawl(url)`，`config_schema` 声明可配 `FIRECRAWL_API_KEY`。
  4. `chart`（tool/category=chart）：tools 含 `generate_chart(spec)`，返回 ECharts HTML。
- `async def ensure_builtin_skills(session)`：按 `key` 幂等 upsert（不存在则插入，存在则更新 manifest 以保持代码为唯一真相）。
- 在 [main.py](file:///root/Documents/trae_projects/botgroup/backend/app/main.py) 的 `lifespan` 中，与 `ensure_bootstrap_user` 并列调用 `ensure_builtin_skills(session)`。

### 4.5 后端 — 工具实现

**新建目录** [backend/app/tools/](file:///root/Documents/trae_projects/botgroup/backend/app/tools/)，含：

- `__init__.py`：`TOOL_HANDLERS: dict[str, Callable]` 注册表 + `async def execute_tool(name, args, config) -> str` 分发器（统一 try/except，错误以字符串返回给 LLM，不抛异常中断讨论）。
- `search.py`：`web_search(query, max_results=5)`。优先 Tavily → 其次 Serper → 兜底 httpx 抓取 DuckDuckGo HTML 并提取结果。返回结构化 Markdown（标题+链接+摘要，**保留来源 URL**）。
- `crawl.py`：`web_crawl(url)`。优先 Firecrawl `/v1/scrape` → 兜底 httpx GET + 正则/简单正文提取（去 script/style/nav，保留标题+正文 Markdown）。
- `chart.py`：`generate_chart(spec)`。`spec` 为 LLM 给出的 JSON（`{type, title, labels[], series[]}`），后端生成**自包含 ECharts HTML 字符串**，并用 ```` ```echarts-html … ``` ```` 代码围栏包裹后返回。

> 依赖：需新增 `httpx`（已有）、`pyyaml`（SKILL.md 解析）、`mcp`（MCP client）。正文提取不引入重量级库，用 `html.parser`/正则实现，避免新增 `beautifulsoup4` 依赖（保持镜像精简）。

### 4.6 后端 — MCP 集成

**新建** [backend/app/services/mcp.py](file:///root/Documents/trae_projects/botgroup/backend/app/services/mcp.py)

- 封装 `mcp` Python SDK 的 client：`connect(server) -> tools`、`call(server, tool_name, args) -> str`。
- 支持 transport：`streamable-http` 与 `sse`（覆盖 LobeHub/marketplace 的远程 server）；`stdio` 首期不做。
- `mcp_tools_to_openai(tools)`：把 MCP tool 的 JSON Schema 转成 OpenAI `tools` 参数格式。
- 连接/拉取 tools 时缓存到 `Skill.manifest["tools"]`，避免每次运行都重连。

**pyproject.toml** 依赖新增：`mcp>=1.0`、`pyyaml>=6.0`。

### 4.7 后端 — 编排改造（核心）

**文件** [backend/app/orchestrator/msghub.py](file:///root/Documents/trae_projects/botgroup/backend/app/orchestrator/msghub.py)

1. `_generate_agent(...)` 增加参数 `tools: list[dict] | None` 与 `skill_context: str | None`，并改为 **tool-calling 循环**：

   - 构造 `messages` 时，把 `skill_context`（knowledge 技能的 instructions + 模板 assets 摘要）拼入 system prompt（追加在 persona 之后、格式约束之前）。
   - `params` 里若 `tools` 非空，加 `tools=tools`、`tool_choice="auto"`。
   - `for step in range(MAX_TOOL_STEPS=5)`：
     - `resp = await client.chat.completions.create(**params)`。
     - 若 `resp.choices[0].message.tool_calls` 存在：逐个 `execute_tool()`，把结果 append 为 `{"role":"tool","tool_call_id":…,"content":…}`，并 yield 一个 `tool_call` SSE 事件（供前端展示「🔧 正在调用 搜索…」）；继续循环。
     - 否则返回 `content`（字符串/列表解析逻辑复用现有）。
   - 循环超限仍未拿到文本，返回最后一条 assistant 文本或固定兜底文案。

2. `run_group_discussion(...)` 增加参数 `bot_skills: dict[int, list[Skill]]`（由 chat.py 查库后传入），在 `message_start` 前对每个 bot 组装 `tools` 与 `skill_context`，传给 `_generate_agent`。

3. 新增手动触发解析：在 `run_group_discussion` 入口，若 `user_prompt` 匹配 `/技能key` 或 `@技能名`，将对应技能排入该轮首个 bot 的强制工具列表（`tool_choice` 指定该工具），其余逻辑不变。

4. 在 `OrchestratorEvent` 增加 `type="tool_call"`（含 `tool_name`、`args`），`chat.py` 转发给前端。

### 4.8 后端 — API 路由

**新建** [backend/app/api/skills.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/skills.py)，`prefix="/api/skills"`：

- `GET /` 列出全部技能（含 bot 关联数量）。
- `POST /` 手动创建自定义 skill（knowledge/tool 两种，供高级用户）。
- `POST /import/skillmd` 上传 `SKILL.md`（multipart file）→ 解析 frontmatter + body → 存为 knowledge 技能。
- `POST /import/skillmd/url` 从 URL 抓取 SKILL.md → 同上。
- `POST /import/mcp` body `{url, transport, name}` → 连接拉 tools → 存为 mcp 技能。
- `GET /community/search?q=` 代理 `skill_market_api_url` 搜索（未配置返回 501）。
- `PATCH /{skill_id}` / `DELETE /{skill_id}`（内置 `builtin=true` 禁止删除）。
- `POST /{skill_id}/assets` 上传模板（存为 `manifest.assets`，支持 docx/md/txt，docx 走现有 MinerU 解析或 `python-docx` 文本提取——首期用 MinerU `parse_pdf` 的扩展路径，未配置 MinerU 时降级为纯文本）。

**扩展** [backend/app/api/bots.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/bots.py)：

- `POST /{bot_id}/skills` body `{skill_ids:[int]}` 批量设置机器人技能。
- `GET /{bot_id}/skills` 返回该机器人已启用技能（含 config）。

**扩展** [backend/app/schemas.py](file:///root/Documents/trae_projects/botgroup/backend/app/schemas.py)：

- 新增 `SkillOut`、`SkillImport`、`BotSkillSet` 等 Pydantic 模型。

**注册路由** [backend/app/main.py](file:///root/Documents/trae_projects/botgroup/backend/app/main.py)：`app.include_router(skills.router, prefix="/api/skills", tags=["skills"])`。

### 4.9 前端 — 导航与页面

**文件** [frontend/components/Sidebar.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/Sidebar.tsx)：`NAV_KEYS` 增加 `{ href: "/skills", key: "nav.skills", icon: "🧩" }`。

**新建** [frontend/app/skills/page.tsx](file:///root/Documents/trae_projects/botgroup/frontend/app/skills/page.tsx)（技能中心）：

- 顶部：技能卡片网格（icon/名称/类型/描述/分类/内置标记/启用机器人数量）。
- Tab 或分区：`全部 / 内置 / 我的技能 / MCP / 社区`。
- 操作：`导入 SKILL.md`（文件上传）、`从 URL 导入`、`添加 MCP server`（填 URL + transport，后台测试连接并导入）、`上传模板`（对 document 技能）、`删除`（内置禁用）。
- 复用 `PageShell`、`Card`、`Badge`、`Dialog`、`Tabs`、`Button`、`useToast`。

### 4.10 前端 — 机器人勾选技能

**文件** [frontend/components/BotFormDialog.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/BotFormDialog.tsx)：

- 在「人设」之后新增「技能」区块：从 `api.listSkills()` 拉取，多选 checkbox；已启用技能可展开查看/编辑 bot 级 config（如自定义模板）。
- 保存时调用 `api.setBotSkills(botId, skillIds)`。

### 4.11 前端 — API 客户端与类型

**文件** [frontend/lib/api.ts](file:///root/Documents/trae_projects/botgroup/frontend/lib/api.ts)：

- 新增类型 `Skill`、`BotSkill`、`McpImportRequest` 等。
- 新增方法 `listSkills / createSkill / importSkillMd / importSkillMdUrl / importMcp / searchCommunity / updateSkill / deleteSkill / uploadSkillAsset / getBotSkills / setBotSkills`。

### 4.12 前端 — 图表安全渲染

**文件** [frontend/components/ChatBubble.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/ChatBubble.tsx) 与 [frontend/lib/markdown.ts](file:///root/Documents/trae_projects/botgroup/frontend/lib/markdown.ts)：

- 后端图表工具输出 ```` ```echarts-html <html>…</html> ``` ```` 围栏。
- 前端渲染 bot 气泡前，先用正则提取 `echarts-html` 围栏内容，替换为 `<iframe sandbox="allow-scripts" srcdoc="…" class="chart-frame">` 占位符，再走 markdown 渲染（markdown `html:false` 仍保留，不放开原始 HTML）。
- 这样图表在 **sandboxed iframe** 内运行，隔离不可信脚本，兼顾「生成图表 HTML」与安全。

### 4.13 前端 — i18n

**文件** [frontend/lib/i18n.tsx](file:///root/Documents/trae_projects/botgroup/frontend/lib/i18n.tsx)：`zh`/`en` 字典补 `nav.skills`、技能中心相关文案、`chat.toolCall`（「正在调用技能…」）。

## 5. 假设与决策

1. **统一 `Skill` 表**：不单独建 `McpServer` 表，MCP server 以 `type="mcp"` 的 `Skill` 记录呈现，连接信息与缓存 tools 存 `manifest`，保持技能中心单一列表。
2. **内置技能 seed 在启动时**（`ensure_builtin_skills`），不在迁移里；与 `ensure_bootstrap_user` 同模式，幂等。
3. **写文档 = knowledge 型**：模板作为 `assets` 注入上下文，LLM 直接输出 Markdown 报告；不实现 docx 二进制导出（作为后续增强）。
4. **图表 = tool 型 + iframe 渲染**：后端产出自包含 ECharts HTML，前端 sandbox iframe 隔离渲染，**不放开 markdown 的 `html:false`**，保证安全。
5. **搜索/爬取数据源**：第三方 key 优先、httpx 兜底（用户已确认）。
6. **MCP transport**：首期支持 `streamable-http` 与 `sse`；`stdio` 不在首期。
7. **社区搜索**：仅当 `SKILL_MARKET_API_URL` 配置时启用，否则前端隐藏搜索、只保留「URL 导入 MCP」与「SKILL.md 导入」。
8. **最小依赖**：后端只新增 `mcp`、`pyyaml`；正文提取/图表生成不引入额外重库。

## 6. 验证步骤

1. `docker compose up -d --build` 启动，确认 `backend` alembic 迁移到 `0007_skills`、`frontend` 构建成功。
2. `curl http://localhost:8000/api/skills` 应返回 4 个内置技能。
3. `curl -X POST http://localhost:8000/api/bots/{id}/skills -d '{"skill_ids":[web_search的id]}'` 给测试机器人启用搜索技能。
4. 在群聊发「帮我查一下 X 的最新进展」→ 观察 SSE 出现 `tool_call` 事件、回复含来源 URL。
5. 发「把这个数据画成柱状图」→ 前端气泡内 sandbox iframe 渲染出 ECharts 图。
6. 上传一份 `测试报告模板.docx` 到 `document_writer`，给「测试工程师」机器人启用；发「按模板写测试报告」→ 输出符合模板结构的 Markdown。
7. `POST /api/skills/import/skillmd` 上传一个 `SKILL.md` → 技能中心出现新 knowledge 技能。
8. `POST /api/skills/import/mcp` 传入一个远程 MCP URL → 成功列出并缓存 tools，机器人可调用。
9. 侧栏出现「技能中心」菜单，页面可浏览/导入/删除技能；机器人编辑弹窗可勾选技能并保存。

## 7. 交付顺序（实现时建议）

1. 后端数据模型 + 迁移 + 配置 + seed + `skills` API（`4.1–4.5, 4.8`）。
2. 工具实现 + 编排 tool-calling 改造 + SSE `tool_call`（`4.5, 4.7`）。
3. MCP 集成 + 社区/导入 API（`4.6, 4.8` 剩余部分）。
4. 前端导航 + 技能中心页面 + api 客户端 + i18n（`4.9, 4.11, 4.13`）。
5. 机器人勾选技能 + 图表 iframe 渲染（`4.10, 4.12`）。
6. 端到端验证（第 6 节）。
