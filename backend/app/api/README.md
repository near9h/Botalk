# backend/app/api

> HTTP 路由层。每个文件一个领域。

## 路由清单

| 文件 | 路径前缀 | 关键端点 |
| --- | --- | --- |
| `auth.py` | `/api/auth` | login / logout / register / me |
| `users.py` | `/api/users` | CRUD + 改密 |
| `bots.py` | `/api/bots` | CRUD + `q/limit/offset` |
| `models.py` | `/api/models` | 转发 NewAPI `/v1/models` |
| `groups.py` | `/api/groups` | CRUD + 机器人管理 |
| `messages.py` | `/api/messages` | 列表 / 删除 |
| `chat.py` | `/api/chat` | SSE 流式 + 历史加载 |
| `runs.py` | `/api/runs` | 流式历史回看 |
| `tasks.py` | `/api/tasks` | 飞书任务代理 |
| `skills.py` | `/api/skills` | 技能中心 |
| `kb.py` | `/api/kb` | KB CRUD + 上传 + chunk 预览 |
| `attachments.py` | `/api/attachments` | 上传 / 下载 / 预览 |
| `policies.py` | `/api/policies` | 群组策略 |
| `audit.py` | `/api/audit` | 审计日志查询 |

## 通用约定

- **顶部 docstring** 列出 `Surface area:` 所有端点（路径 + 用途）
- **Pydantic schema** 放在文件顶部（而非全局 schemas.py）—— 保证模块可独立读
- **错误处理**：路由层用 `HTTPException`；service 层抛自定义异常
- **审计**：依赖 `_audit_ctx`，service 层 `audit_service.log()`
- **鉴权**：`Depends(require_user)` 或 `Depends(require_admin)`

## 最近改动

| 日期 | commit | 摘要 |
| --- | --- | --- |
| 2026-09-20 | `ae0bae1` | KB 重命名 `PATCH /api/kb/{id}` |
| 2026-09-19 | `6756b4b` | bots 搜索 + 分页 |

详见 [.trae/documents/06-implementation/](../.trae/documents/06-implementation/)。