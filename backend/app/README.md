# backend/app

> 后端应用代码。FastAPI + SQLAlchemy 2.x async + Alembic。

---

## 模块索引

| 子目录 | 作用 | 模块 README |
| --- | --- | --- |
| `api/` | HTTP 路由（14 个模块） | [api/README.md](api/README.md) |
| `orchestrator/` | 多 bot 群聊调度 | [orchestrator/README.md](orchestrator/README.md) |
| `services/` | 跨模块业务（10+ 个） | [services/README.md](services/README.md) |
| `skills/` | 技能注册中心 | [skills/README.md](skills/README.md) |
| `workers/` | 后台 worker（ingest） | [workers/README.md](workers/README.md) |
| `tools/` | bot 可调工具 | [tools/README.md](tools/README.md) |
| `db/` | ORM 模型 + 会话 | [db/README.md](db/README.md) |

## 顶层文件

| 文件 | 作用 |
| --- | --- |
| `main.py` | FastAPI 入口；启动时 `ensure_bootstrap_user` |
| `config.py` | pydantic-settings，从 `.env` 加载 |
| `auth.py` | JWT + bcrypt + `require_user/admin` 依赖 |
| `schemas.py` | 跨模块共享的 Pydantic schema |

## 启动顺序

1. `entrypoint.sh` → alembic upgrade head
2. `uvicorn app.main:app --host 0.0.0.0 --port 8000`
3. 应用启动钩子 `ensure_bootstrap_user`（首次建 admin）

## 文档入口

- 架构：[`.trae/documents/04-architecture/`](../.trae/documents/04-architecture/)
- ADR：[`.trae/documents/adr/`](../.trae/documents/adr/)
- 实现记录：[`.trae/documents/06-implementation/`](../.trae/documents/06-implementation/)