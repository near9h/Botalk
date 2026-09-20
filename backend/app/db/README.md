# backend/app/db

> 数据库层：ORM 模型 + 会话工厂。

## 文件

| 文件 | 作用 |
| --- | --- |
| `models.py` | 所有 SQLAlchemy ORM 模型（15 张表） |
| `session.py` | `get_session` 依赖；async engine |

## 表清单（与 [`../../.trae/documents/04-architecture/README.md` §5](../../.trae/documents/04-architecture/README.md#5-数据架构postgresql) 同步）

| 表 | 作用 |
| --- | --- |
| `users` | 用户 + 角色 + 状态 |
| `bots` | 机器人（model + persona + temperature） |
| `groups` | 群组（mode + max_rounds） |
| `group_members` | 群组成员（含 bot / 观察者） |
| `messages` | 消息（含引用 JSON） |
| `attachments` | 通用附件（KB / chat 共用） |
| `runs` | 任务运行实例（含多轮 + tokens_used） |
| `knowledge_bases` | 知识库（scope + is_public + ragflow_dataset_id 兼容列） |
| `kb_documents` | KB 内文档（status: pending/parsing/ready/failed） |
| `kb_chunks` | KB 切片（bbox_json + snippet + embedding） |
| `bot_kb` | bot ↔ KB 挂载表 |
| `skills` | 技能定义（注册中心持久化） |
| `bot_skills` | bot ↔ 技能挂载 |
| `system_policies` | 群组策略 / 防火墙（按 group_id 应用） |
| `audit_logs` | 全量操作审计 |

## 迁移

```bash
cd backend
alembic revision --autogenerate -m "msg"
alembic upgrade head
```

CI / 容器启动自动 `upgrade head`（`entrypoint.sh`）。