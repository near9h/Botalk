# backend/app/db

> 数据库层：ORM 模型 + 会话工厂。

## 文件

| 文件 | 作用 |
| --- | --- |
| `models.py` | 所有 SQLAlchemy ORM 模型（约 15 张表） |
| `session.py` | `get_session` 依赖；async engine |

## 表清单

| 表 | 作用 |
| --- | --- |
| `users` | 用户 + 角色 + 状态 |
| `bots` | 机器人 |
| `groups` | 群组 |
| `group_bots` | 群组-机器人 多对多 |
| `messages` | 消息（含引用 JSON） |
| `attachments` | 通用附件（KB / chat 共用） |
| `knowledge_bases` | 知识库 |
| `kb_documents` | KB 内文档（含 status: pending/parsing/ready/failed） |
| `kb_chunks` | KB 切片（含 bbox_json + snippet） |
| `audit_log` | 全量操作审计 |
| `policies` | 群组策略 |
| `skills` | 技能定义 |
| `runs` | 任务运行历史 |
| `tasks` | 飞书任务镜像 |
| `mcp_*` | MCP 协议相关（探索性） |

## 迁移

```bash
cd backend
alembic revision --autogenerate -m "msg"
alembic upgrade head
```

CI / 容器启动自动 `upgrade head`（`entrypoint.sh`）。