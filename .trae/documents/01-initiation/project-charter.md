# 多机器人多模型群聊工具：技术栈与开发方案

## Summary

基于《多机器人群聊工具开源方案调研.md》底稿的判断，本项目目标是用 **AgentScope MsgHub 做讨论编排引擎 + 自研 React 前端 + PostgreSQL 持久层 + Docker Compose 一键部署**，打造一个"配置多机器人角色 → 建群 → 提出问题 → 机器人按策略互相讨论 → 流式输出"的产品。

调用层对接用户自有的 **NewAPI（QuantumNous/new-api）** 网关：所有模型调用走标准 OpenAI 兼容协议（`/v1/chat/completions` + `Bearer` 鉴权），项目本身不接各家厂商 SDK，单一依赖点。

---

## Current State Analysis

- 项目目录 `/root/Documents/trae_projects/botgroup` 当前为空，仅有底稿 md 一份。属于从零起步。
- 底稿调研已锁定三个核心事实：
  1. "机器人互相讨论"是分水岭功能，需要 GroupChat/MsgHub 这类编排引擎；产品级开源里 botgroup.chat / SillyTavern 最贴合，但前者体量小、后者 AGPL 不利商用。
  2. NewAPI 是用户已部署好的 LLM 网关，对外暴露 OpenAI 兼容协议，业务侧**只把它当一个 OpenAI 兼容的 base_url + sk-key** 即可，不需自建适配层。
  3. 框架侧 AG2 / AgentScope / CrewAI 是三选一范畴，本方案按用户决策选 AgentScope（自带 FastAPI 服务化 + 预构建 Web UI，中文文档，Apache-2.0）。

---

## Proposed Changes

### 总体架构

```
┌────────────────────────────────────────────────────────────────┐
│                    Docker Compose (单机部署)                    │
│                                                                │
│  ┌──────────┐    SSE/WebSocket    ┌────────────────────────┐   │
│  │ frontend │ ◄────────────────►  │     backend (FastAPI)  │   │
│  │  React   │                     │   + AgentScope MsgHub  │   │
│  │ Next.js  │                     │   + 编排服务            │   │
│  └──────────┘                     └──────────┬─────────────┘   │
│       ▲                                     │                 │
│       │ REST                                ▼                 │
│       │                              ┌─────────────┐          │
│       └─────── 角色/群组/历史 ─────► │ PostgreSQL  │          │
│                                      └─────────────┘          │
│                                              │                │
│                                              ▼                │
│                                  ┌────────────────────┐       │
│                                  │  NewAPI 网关（外部）│       │
│                                  │  /v1/chat/completions │    │
│                                  └────────────────────┘       │
└────────────────────────────────────────────────────────────────┘
```

### 1. 后端（FastAPI + AgentScope）

**目录结构**：

```
backend/
├── app/
│   ├── main.py                  # FastAPI 入口，挂载路由 + lifespan 初始化 AgentScope
│   ├── config.py                # 环境变量：NEWAPI_BASE_URL/KEY、DB URL、AGENTSCOPE 配置
│   ├── db/
│   │   ├── models.py            # SQLAlchemy ORM：User/Bot/Group/GroupMember/Message/Run
│   │   ├── session.py           # async engine + session factory
│   │   └── migrate.py           # alembic 迁移入口
│   ├── api/
│   │   ├── bots.py              # CRUD：机器人（角色）管理
│   │   ├── groups.py            # CRUD：群组 + 群成员管理
│   │   ├── messages.py          # 历史消息查询
│   │   └── chat.py              # SSE 端点 /api/chat/stream，发起讨论
│   ├── agentscope_app/
│   │   ├── bots.py              # 把数据库中的 Bot 转换为 AgentScope Agent
│   │   ├── msghub.py            # MsgHub 编排：round_robin / auto(LLM 选) / manual 三种策略
│   │   ├── runner.py            # 运行一次群聊讨论，输出流式事件
│   │   └── streaming.py         # 把 AgentScope 流式回调转为 SSE 事件
│   └── schemas/                 # Pydantic 模型
├── pyproject.toml               # 依赖：fastapi / agentscope / sqlalchemy[asyncio] / asyncpg
├── Dockerfile
└── .env.example                 # NEWAPI_BASE_URL、NEWAPI_API_KEY、DATABASE_URL
```

**核心设计点**：

- **NewAPI 调用层**：AgentScope 内置的 `OpenAIChatModel` 直接兼容 OpenAI 协议，初始化时 `api_key=NEWAPI_API_KEY`、`base_url=NEWAPI_BASE_URL`（如 `https://your-newapi.com/v1`）、`model=<用户在 NewAPI 中配置的模型名>`，不写任何厂商适配代码。
- **机器人定义**：每个 Bot 是 DB 的一条记录 + AgentScope 的一个 Agent。Bot 字段：`id / name / avatar / persona（系统提示词） / model（新 API 中的模型名） / temperature / parameters_json`。
- **群组编排**：在 `msghub.py` 用 AgentScope 的 MsgHub（pipeline + broadcast）组装多 Agent。MsgHub 的"动态增删参与者"原语正好对应"建群 / 拉人 / 踢人"。
- **发言调度策略**（落地 ⑤ 的核心）：
  - `round_robin`：固定顺序轮流，按数据库中群成员的 join 顺序；
  - `auto`（默认）：用一个小模型（NewAPI 上配的 cheap 模型）读当前对话历史，决策下一个发言者；
  - `manual`：前端用户@某个机器人，被@者下一轮必发言；
  - **终止条件**：`max_rounds`（默认 6 轮）+ `synthesizer` 角色收尾（可选）+ 用户主动中断。
- **流式输出**：`runner.py` 订阅 AgentScope 的流式回调，转为 SSE 事件 `event: token / event: message_end / event: run_end`，前端用 EventSource 消费。
- **历史持久化**：每条消息落库 `messages` 表（`role` / `bot_id` / `content` / `token_usage` / `created_at`），同时在 AgentScope Memory 中保留短期上下文用于单轮讨论。

### 2. 前端（Next.js + Vercel AI SDK 风格流式渲染）

**目录结构**：

```
frontend/
├── app/
│   ├── page.tsx                 # 群列表
│   ├── group/[id]/page.tsx      # 单群聊视图：消息流 + 输入框 + @机器人
│   ├── bots/page.tsx            # 机器人管理后台
│   └── settings/page.tsx        # 用户设置
├── components/
│   ├── MessageBubble.tsx        # 区分用户/不同机器人的气泡 + 头像
│   ├── ChatInput.tsx            # @机器人选择器
│   ├── BotEditor.tsx            # 机器人人设 / 模型 / 参数编辑表单
│   └── StreamingMessage.tsx     # 流式打字效果
├── lib/
│   ├── api.ts                   # fetch 封装
│   └── sse.ts                   # EventSource 工具，支持中断
├── package.json
├── Dockerfile                   # 多阶段构建，运行时 node:slim + next start
└── .env.example                 # NEXT_PUBLIC_API_BASE
```

**核心设计点**：

- 群聊视图参考 LibreChat / LobeChat 的消息流，机器人和用户消息混排；
- 输入框支持 `@机器人` 触发 manual 模式；
- 流式渲染直接用浏览器 EventSource，零依赖对接后端 SSE。

### 3. 数据库（PostgreSQL）

**核心表设计**：

| 表 | 关键字段 | 说明 |
|---|---|---|
| `bots` | id, name, avatar_url, persona(text), model, temperature, params(jsonb), created_at | 机器人 = 模型 + 人设 |
| `groups` | id, name, description, owner_id, mode(round_robin/auto/manual), max_rounds, created_at | 群组 |
| `group_members` | group_id, bot_id, join_order, joined_at | 群成员（多对多） |
| `messages` | id, group_id, role(user/bot/system), bot_id(nullable), content(text), token_usage(int), created_at | 单条消息 |
| `runs` | id, group_id, status(running/done/error), started_at, finished_at, total_tokens | 单次群聊讨论会话 |

- 使用 SQLAlchemy 2.x async + asyncpg；
- 用 Alembic 做迁移，初始化时执行 `alembic upgrade head`；
- 预留 `jsonb` 字段给 `params` 和未来扩展（如工具调用、记忆）。

### 4. 部署（Docker Compose）

**根目录文件**：

```
docker-compose.yml
.env.example
README.md
backend/Dockerfile
frontend/Dockerfile
```

**docker-compose.yml 服务**：

- `postgres`：官方 `postgres:16-alpine`，挂载 `./data/postgres:/var/lib/postgresql/data`，健康检查；
- `backend`：构建 `backend/Dockerfile`，depends_on postgres healthy，端口 8000；
- `frontend`：构建 `frontend/Dockerfile`，端口 3000；
- 可选 `nginx`：反向代理 80/443，对外只暴露一个端口（生产推荐）。

**启动流程**（写到 README）：

```bash
cp .env.example .env
# 编辑 .env：填 NEWAPI_BASE_URL、NEWAPI_API_KEY、POSTGRES_PASSWORD
docker compose up -d
# 访问 http://localhost:3000
```

后端容器启动时自动跑 Alembic 迁移；前端 build 时通过 `NEXT_PUBLIC_API_BASE` 注入后端地址。

---

## Assumptions & Decisions

- **NewAPI 部署假设**：用户已自建好 NewAPI 并配置多模型，本项目只通过 `OPENAI_BASE_URL` + `OPENAI_API_KEY` 两个变量对接，**不在项目内处理模型路由、不落 token 计费**（NewAPI 自己做）。
- **AGPL-3.0 影响规避**：NewAPI 和 SillyTavern 都是 AGPL-3.0，但 NewAPI 部署在用户自己侧、用户自己的数据流经它，本项目代码不复制 NewAPI 源码、不修改它、不 fork 它，只是把它当 HTTP API 调用，因此**本项目不受 NewAPI AGPL 传染**；前端/后端/数据库代码均为 MIT/Apache 友好协议，本项目拟采用 MIT License。
- **不做**：用户系统（鉴权/SSO/多租户审计）—— 简化为单用户自托管形态；MCP 工具调用—— 留作 v2；多用户权限—— 同上。
- **讨论默认策略**：auto（LLM 选下一个发言者）+ max_rounds=6，可在群配置里改。
- **流式传输协议**：用 SSE 而非 WebSocket—— 实现最简、AgentScope 流式回调天然契合、断线重连方便；如未来要双向（用户实时打断机器人）再升级 WS。

---

## Verification Steps

按以下顺序验证：

1. **NewAPI 连通性**：`curl $NEWAPI_BASE_URL/v1/models -H "Authorization: Bearer $NEWAPI_API_KEY"` 返回模型列表。
2. **后端启动**：`docker compose up backend` 后访问 `http://localhost:8000/docs` 看到 Swagger。
3. **机器人 CRUD**：在 Swagger 里 POST `/api/bots` 创建一个机器人（model 填 NewAPI 中真实存在的模型名），GET 列表能查到。
4. **群聊讨论端到端**：
   - POST `/api/groups` 建群，把刚才的机器人加进群；
   - POST `/api/chat/stream`（SSE）发一个问题；
   - 用 `curl -N` 验证 SSE 流能持续输出 `event: token` 事件，最终 `event: run_end`；
   - 检查 `messages` 表有对应记录。
5. **前端集成**：访问 `http://localhost:3000`，能看到消息流逐字渲染、不同机器人不同头像气泡。
6. **持久化**：重启 backend 容器后历史消息仍能从数据库查到。

---

## 实施里程碑（建议顺序）

1. **M1 - 骨架（半天）**：docker-compose.yml + backend/frontend Dockerfile + postgres + FastAPI `/health` + Next.js 首页"Hello"。
2. **M2 - 数据层（半天）**：SQLAlchemy 模型 + Alembic 迁移 + bots/groups CRUD API（Swagger 验证）。
3. **M3 - 集成 NewAPI（半天）**：AgentScope 初始化接 NewAPI，单 Agent 流式调用通，确认能拿到模型回复。
4. **M4 - MsgHub 编排（1 天）**：MsgHub 组装多 Agent，round_robin + auto 两种策略落地，流式 SSE 端到端通。
5. **M5 - 前端群聊视图（1 天）**：消息流 + 输入框 + @机器人，流式渲染。
6. **M6 - 机器人后台（半天）**：BotEditor 表单 + 群成员管理。
7. **M7 - 收尾（半天）**：README、.env.example、健康检查、错误日志、移动端响应式适配。

总计约 4–5 天出可演示原型。