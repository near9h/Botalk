# Botalk — 多机器人多模型群聊工具

配置多个 AI 机器人（每个机器人 = 一个模型 + 一段人设）→ 建群把它们拉到一起 → 提出问题，机器人按策略互相讨论、流式输出。

调用层对接你已部署的 **NewAPI**（OpenAI 兼容协议），系统本身不接各家厂商。


<img width="2256" height="1251" alt="image" src="https://github.com/user-attachments/assets/06091722-bdb2-41fb-a7b9-86d5d0c53152" />
<img width="2560" height="1229" alt="24e70db00412b8a9b5b841a222344eee" src="https://github.com/user-attachments/assets/2ed2ad5d-8366-400b-a08c-0bfb60384b85" />
<img width="2256" height="1251" alt="image" src="https://github.com/user-attachments/assets/f465cbd9-34c9-4f91-af8b-8603f40ce1e3" />
<img width="2256" height="1251" alt="image" src="https://github.com/user-attachments/assets/cb4f8343-2d10-47d1-8419-2d50b08dc8ef" />



## 技术栈

- **后端**：FastAPI + SQLAlchemy 2.x(async) + Alembic + AgentScope MsgHub
- **前端**：Next.js 14 (App Router) + 原生 EventSource 流式渲染
- **数据库**：PostgreSQL 16
- **部署**：Docker Compose（单机一键起）
- **License**：MIT

## 一键启动

`.env.example` 是模板；复制成 `.env` 后填你自己的 NewAPI URL + Key，再 `docker compose up -d --build` 试用：

```bash
cp .env.example .env
# 编辑 .env：把 NEWAPI_BASE_URL / NEWAPI_API_KEY / AUTH_BOOTSTRAP_PASSWORD 等占位符替换成你的真实值
docker compose up -d --build
docker compose logs -f backend   # 确认 alembic upgrade head 完成
```

```bash
# 看启动日志（确认 backend 完成 alembic 迁移、frontend 完成 Next.js 构建）
docker compose logs -f backend
docker compose logs -f frontend

# 浏览器：
#   http://localhost:3500       前端（端口由 .env 的 FRONTEND_PORT 控制）
#   http://localhost:8000/docs  Swagger API 文档
```

### 端口冲突

修改 [.env](file:///root/Documents/trae_projects/botgroup/.env) 中的 `FRONTEND_PORT` / `BACKEND_PORT` 即可，compose 文件会自动跟随。改完记得 `docker compose up -d --build`（前端改端口需要重新构建镜像，因为 `next start` 的监听端口由构建期注入的 `PORT` 环境变量决定）。

### 已验证可用的 NewAPI 模型（来自实际探测）

| 模型 ID | 备注 |
|---|---|
| `gemini-2.5-flash` | 带思考（reasoning_tokens 占大头），单次调用可达 1.5k+ tokens |
| `agnes-2.5-flash` / `agnes-3.0-flash` | |
| `claude-3-5-sonnet-20240620` | |
| `gpt-4o` | |
| `gpt-5.4-mini` | |
| `MiniMax-M2.7` / `MiniMax-M3` | |

后端默认每次调用 `max_tokens=2048`、超时 120s，可在 `.env` 中调 `MAX_TOKENS_PER_CALL` / `REQUEST_TIMEOUT_SECONDS`。

## 使用流程

1. **新建机器人**：进 `/bots`，填名称、模型（NewAPI 中已配置的模型名）、人设、温度。
2. **新建群组**：首页点 "+ 新建群组"，输入名称，进入群组页。
3. **拉机器人入群**：左侧"添加机器人"下拉里选一个，点"加入群"。
4. **开始讨论**：在输入框发消息，机器人按 `auto` / `round_robin` / `manual` 模式轮流发言；用 `@机器人名` 可以指定某个机器人发言。
5. **查看历史**：所有消息自动落库到 PostgreSQL，重启不丢失。

## 发言调度策略

在群组创建/编辑时选择：

- `auto`（默认）：一轮内所有机器人都按加入顺序发言，LLM 决定何时停止；
- `round_robin`：每轮只有 1 个机器人发言，按加入顺序轮换；
- `manual`：仅当用户在消息中 `@机器人名` 时才让被@的机器人发言，否则退回轮换。

`max_rounds` 控制最大轮次（默认 6），到点自动停。

## 目录结构

```
botgroup/
├── backend/                  # FastAPI 服务
│   ├── app/
│   │   ├── main.py           # 入口
│   │   ├── config.py         # 环境变量
│   │   ├── db/               # SQLAlchemy 模型 / 会话
│   │   ├── api/              # 路由：bots / groups / messages / chat
│   │   ├── agentscope_app/   # 编排引擎（msghub / runner / bots）
│   │   └── schemas.py        # Pydantic 模型
│   ├── alembic/              # 数据库迁移
│   ├── alembic.ini
│   ├── pyproject.toml
│   ├── Dockerfile
│   └── entrypoint.sh         # 容器启动：alembic upgrade head && uvicorn
├── frontend/                 # Next.js 应用
│   ├── app/                  # 路由
│   ├── lib/api.ts            # fetch + EventSource 工具
│   └── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## 验证步骤（端到端）

```bash
# 1. 验证 NewAPI 连通性
curl $NEWAPI_BASE_URL/v1/models -H "Authorization: Bearer $NEWAPI_API_KEY"

# 2. 验证后端健康
curl http://localhost:8000/health

# 3. 创建机器人（model 替换成 NewAPI 中真实存在的模型名）
curl -X POST http://localhost:8000/api/bots \
  -H 'Content-Type: application/json' \
  -d '{"name":"助手A","persona":"你是简洁的助手","model":"gpt-4o-mini","temperature":0.7}'

# 4. 创建群组并加入机器人
curl -X POST http://localhost:8000/api/groups \
  -H 'Content-Type: application/json' \
  -d '{"name":"讨论室","mode":"auto","max_rounds":4,"bot_ids":[1]}'

# 5. 流式发起讨论
curl -N -X POST http://localhost:8000/api/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"group_id":1,"prompt":"你好"}'
```

## 排错

- **后端起不来**：先 `docker compose logs backend`，多数情况是 `alembic upgrade` 失败，检查 `NEWAPI_*` 与 `DATABASE_URL` 环境变量。
- **LLM 不响应**：直接用上面 `curl /v1/models` 验证 NewAPI Key 是否有效。
- **前端连不上后端**：浏览器开 DevTools 看网络请求；`.env` 里 `NEXT_PUBLIC_API_BASE` 必须是浏览器能访问的地址（不要用容器内部 `backend:8000`）。

## License

MIT
