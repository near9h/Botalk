# 用户管理 + 审计日志 模块实施计划

## 摘要

在现有 BotGroup 单用户自托管基础上，扩展为多用户平台：

1. **用户管理** — 完整 RBAC：管理员可新增/启停/重置密码/删除普通用户，引入 `role`（admin / user）与 `status`（active / disabled）。
2. **Bot 分类** — 在 `bots` 表新增 `owner_id`（FK users.id，NULL=系统默认）与 `scope`（system / user）字段；现有 `is_system`/`is_protected` 行为向下兼容映射到 `scope=system`。**普通用户只能看到 system bot 与自己创建的 bot**；管理员看全部。
3. **群组（对话）隔离 + 随机化 ID** — 在 `groups` 表加 `public_id`（12 字符 base62，URL/API 用，替换原递增整数 id 出参）、`owner_id`、`scope` 字段；**普通用户只能看到自己创建的群组**，管理员看全部；`runs` / `messages` / `attachments` 通过内部整数 `group_id` 透明跟随可见性。
4. **审计日志** — 新增 `audit_logs` 表，覆盖所有写操作（登录、用户增删改、bot/技能/群组/任务/技能市场的写操作），多维筛选（actor / action / target / 时间段），保留 90 天，后台清理。

## 当前状态分析（基于 Phase 1 探索）

| 现状 | 出处 |
|---|---|
| 已有 `users` 表（id/username/email/password_hash/created_at），单一 admin bootstrap | [0004_users.py](file:///root/Documents/trae_projects/botgroup/backend/alembic/versions/0004_users.py) |
| Auth 已有 bcrypt + JWT cookie + `get_current_user` / `require_user` / `ensure_bootstrap_user` | [auth.py](file:///root/Documents/trae_projects/botgroup/backend/app/auth.py) |
| Auth API：`/api/auth/{login,logout,register,me}`，`register` 仅当 users 表为空时开放 | [api/auth.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/auth.py) |
| `bots` 表已有 `is_system` / `is_protected` 字段；system 不可删改，protected 不可改名/模型/删 | [models.py](file:///root/Documents/trae_projects/botgroup/backend/app/db/models.py) [0010_protected_bots.py](file:///root/Documents/trae_projects/botgroup/backend/alembic/versions/0010_protected_bots.py) |
| Bot API：`list_bots` 返回所有人共见；`update`/`delete` 拒绝 system/protected 的 rename 与 delete | [api/bots.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/bots.py) |
| 前端 Sidebar、BotCard、BotFormDialog 完全没有 owner/role 概念；bot 列表全用户共享 | [Sidebar.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/Sidebar.tsx) [BotFormDialog.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/BotFormDialog.tsx) [bots/page.tsx](file:///root/Documents/trae_projects/botgroup/frontend/app/bots/page.tsx) |
| 已有 12 个 alembic 迁移，最后一次 `0012_task_share_token.py` | [backend/alembic/versions/](file:///root/Documents/trae_projects/botgroup/backend/alembic/versions/) |
| 无任何 audit/operation log 存在 | `Grep AuditLog|audit_log` 命中 0 条 |

## 提议变更（详细）

### A. 数据库迁移 `0013_rbac_and_audit.py`

新文件 [0013_rbac_and_audit.py](file:///root/Documents/trae_projects/botgroup/backend/alembic/versions/0013_rbac_and_audit.py)

**A.0 扩展 `groups` 表（用户隔离的关键 + 随机化 ID）**

按用户最新要求：
1. "普通用户只能看到自己设置的群组，管理员能看到所有" — 加 owner_id + scope 字段
2. "群组的groupid现在是递增的数字，改成随机id" — 把 `groups.id` 改成 12 字符 base62 随机 token（与现有 `runs.share_token` 同方案），避免 URL 泄漏分组量级和创建顺序

```sql
-- 1. 先把现有 id 转成整数列，作为内部主键保留
ALTER TABLE groups ADD COLUMN public_id VARCHAR(16) UNIQUE;

-- 2. 给存量 group 生成 random public_id
-- (alembic 用 Python + secrets 逐行 backfill，与 0012_task_share_token 同套路)

-- 3. 加 owner_id + scope
ALTER TABLE groups
  ADD COLUMN owner_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  ADD COLUMN scope    VARCHAR(16) NOT NULL DEFAULT 'user';
CREATE INDEX ix_groups_public_id ON groups(public_id);
CREATE INDEX ix_groups_owner      ON groups(owner_id);
CREATE INDEX ix_groups_scope      ON groups(scope);
```

升级逻辑：
- 老部署里所有现存的 group → backfill 一段 12 字符的 base62 随机 `public_id`（与 share_token 同熵），`scope='user'`，`owner_id` 指向当前 bootstrap admin（用 `SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1` 兜底）。
- **同时把所有外键（`group_members.group_id` / `messages.group_id` / `runs.group_id` / `attachments.group_id`）从 INTEGER 改成指向新列还是 INTEGER？→ 保留 INTEGER 内部主键，外键不动**；`public_id` 仅用于 wire-facing（URL、API 入参），DB join 仍用整数 id。
- 整数 id **不再对外暴露**（不出现在 API 出参），只出现在日志和审计里便于 DBA 排查。
- 前端从 `group.id` 改成 `group.public_id`；URL 从 `/group/123` 改成 `/group/Ab3kQ9zX2pL7`。
- **下划线**：API 仍支持按 `public_id` 查询；server 端收到 public_id 后查回 integer id 再做外键关联。

**A.1 扩展 users 表**

```sql
ALTER TABLE users
  ADD COLUMN role          VARCHAR(16) NOT NULL DEFAULT 'user',  -- 'admin'|'user'
  ADD COLUMN status        VARCHAR(16) NOT NULL DEFAULT 'active', -- 'active'|'disabled'
  ADD COLUMN display_name  VARCHAR(128),
  ADD COLUMN last_login_at TIMESTAMPTZ,
  ADD COLUMN created_by_id INTEGER REFERENCES users(id);
CREATE INDEX ix_users_role ON users(role);
CREATE INDEX ix_users_status ON users(status);
```

升级逻辑：
- 若当前 users 表非空且没有 `is_admin` 字段：把所有现有用户的 `role` 置为 `'admin'`（向后兼容，老部署管理员无感升级）。
- 业务命名约定：`is_admin` 字段名 → 用 `role` 枚举替代；后续如需 `auditor`/`viewer` 等只改枚举值即可。

**A.2 bots 表加 owner_id + scope**

```sql
ALTER TABLE bots
  ADD COLUMN owner_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  ADD COLUMN scope    VARCHAR(16) NOT NULL DEFAULT 'user';
CREATE INDEX ix_bots_owner ON bots(owner_id);
CREATE INDEX ix_bots_scope ON bots(scope);
```

升级逻辑：
- `is_system=true` 的 bot → `scope='system'`，`owner_id=NULL`
- `is_protected=true` 的 bot（产品级默认 bot）→ `scope='system'`，`owner_id=NULL`
- 普通 bot → `scope='user'`，`owner_id` 由调用方在 create 时填入（API 层强校验）

**A.3 新表 audit_logs**

```sql
CREATE TABLE audit_logs (
  id           BIGSERIAL PRIMARY KEY,
  occurred_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
  actor_name   VARCHAR(64) NOT NULL,            -- 冗余存，防 user 被删后看不到
  actor_role   VARCHAR(16) NOT NULL,            -- 同上
  action       VARCHAR(64) NOT NULL,            -- e.g. 'user.create','bot.delete'
  target_type  VARCHAR(32) NOT NULL,            -- 'user'|'bot'|'skill'|'group'|'task'|'skill_market'|'auth'
  target_id    VARCHAR(64),                     -- 字符串允许复合主键或 share_token
  target_name  VARCHAR(256),
  ip           VARCHAR(45),                     -- IPv6 安全
  user_agent   VARCHAR(512),
  status       VARCHAR(16) NOT NULL,            -- 'success'|'failure'
  detail       JSONB NOT NULL DEFAULT '{}'::jsonb  -- diff / 错误堆栈 / 来源 trace_id
);
CREATE INDEX ix_audit_occurred_at  ON audit_logs(occurred_at DESC);
CREATE INDEX ix_audit_actor        ON audit_logs(actor_id, occurred_at DESC);
CREATE INDEX ix_audit_action       ON audit_logs(action, occurred_at DESC);
CREATE INDEX ix_audit_target       ON audit_logs(target_type, target_id);
```

### B. 后端 — 权限基础设施

**B.1 扩展 auth 层** — [app/auth.py](file:///root/Documents/trae_projects/botgroup/backend/app/auth.py)

新增 `require_admin` 依赖：
```python
async def require_admin(user: Annotated[User, Depends(require_user)]) -> User:
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user
```

**B.2 审计日志服务** — 新文件 [app/services/audit.py](file:///root/Documents/trae_projects/botgroup/backend/app/services/audit.py)

```python
class AuditContext:
    """从 Request 里抽 ip/ua/actor 一次性传入"""
    actor: User | None
    ip: str
    user_agent: str

async def log(session, ctx: AuditContext, *, action: str,
              target_type: str, target_id: str | None = None,
              target_name: str | None = None, status: str = "success",
              detail: dict | None = None) -> None:
    """fire-and-forget; 不抛异常阻断主业务"""

async def cleanup_old_logs(session, *, retention_days: int = 90) -> int:
    """返回删除条数; 由 lifespan 或 cron 触发"""
```

提供 FastAPI 依赖 `audit_ctx(request, user)` 自动从 `request.client.host` 与 `request.headers["user-agent"]` 构造 `AuditContext`。

**B.3 日志清理调度**

在 [main.py lifespan](file:///root/Documents/trae_projects/botgroup/backend/app/main.py) 启动时增加：每天 0 点后台任务 `cleanup_old_logs(retention_days=90)`，避免长跑进程无限堆积日志。

### C. 用户管理 API — 新文件 [app/api/users.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/users.py)

| Method | Path | 权限 | 行为 |
|---|---|---|---|
| GET    | `/api/users`               | admin          | 列出所有用户（含 disabled） |
| POST   | `/api/users`               | admin          | 新增用户，密码默认 12 位随机（管理员可覆盖） |
| GET    | `/api/users/me`            | self           | 当前用户详情（已存在 `/api/auth/me`，此为扩展） |
| GET    | `/api/users/{id}`          | admin          | 单用户详情 |
| PATCH  | `/api/users/{id}`          | admin          | 修改 display_name/email/role/status |
| POST   | `/api/users/{id}/reset-password` | admin   | 管理员重置密码（返回新密码） |
| DELETE | `/api/users/{id}`          | admin          | 软删除：status='disabled'；同时撤销未完成任务（不级联删数据） |
| POST   | `/api/users/{id}/enable`   | admin          | status=active

新增 Pydantic schemas 在 [schemas.py](file:///root/Documents/trae_projects/botgroup/backend/app/schemas.py)：
- `UserOut`（扩展 MeOut：含 role/status/display_name/last_login_at/created_by_id）
- `UserCreate`, `UserUpdate`, `UserResetPasswordOut`

每个写操作都包 `await audit.log(...)`。

**保护规则**：
- 不能删除最后一个 admin（API 层防御性检查）
- admin 也不能禁用自己
- 不能把最后一个 admin 降级

### D. Bot 分类 — 修改 [app/api/bots.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/bots.py)

**D.1 GET /api/bots**
- admin → 返回所有 bots（含各 owner 的 user bot）
- 普通用户 → 返回 `scope='system'` OR `owner_id = current_user.id`
- 前端：卡片右上角加角色标签徽章 `系统 / 我的 / 其他用户`

**D.2 POST /api/bots**
- 必须 `user: User = Depends(require_user)`
- 自动 `owner_id = user.id, scope='user'`
- admin 可显式传 `scope='system'` 创建共享 bot（但仍受 protected 改名保护）

**D.3 PATCH /api/bots/{id}
- 非 owner 且非 admin → 403
- system bot：保留现有 protected 校验（admin 也不能改 name/model）
- owner 普通用户：可改 emoji/persona/temperature/params；改不了 scope/owner

**D.4 DELETE /api/bots/{id}
- system bot：保留现有 403
- owner 或 admin：可删

**D.5 BotCard、BotFormDialog、GroupWizard 适配**：
- GroupWizard 加 `availableBots` 过滤（只显示可见的 bot）
- BotCard 显示 owner 标签（系统默认 / @username / 我的）
- 删除按钮对非 owner 普通用户禁用

### E. 群组（对话）隔离 — 修改 [app/api/groups.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/groups.py)

按用户最新要求"普通用户只能看到自己设置的群组，管理员能看到所有"：

**E.0 public_id 处理（随机化 ID）**

- 所有 group 出参用 `public_id` 字段（保留 `id` 字段但仅做内部参考；考虑直接不再出 `id`，避免误用）
- 所有 group 入参（路径、查询）都接受 `public_id`；server 端查回 integer id
- 内部 SQL join / 外键仍用 integer id

新增 helper（与现有 `runs` 的 `_resolve_run` 同套路）：
```python
# app/api/groups.py
async def resolve_group(session, token: str) -> Group | None:
    """public_id (12 char base62) → Group; None if not found."""
    return (await session.execute(
        select(Group).where(Group.public_id == token)
    )).scalar_one_or_none()
```

**E.1 GET /api/groups**
```python
if user.role == "admin":
    return all groups
else:
    return groups where scope='system' OR owner_id == user.id
```
- 与 bot 隔离逻辑对齐：system 群组（admin 显式创建的）全用户可见；普通用户的私有群组互相不可见。

**E.2 POST /api/groups**
- 自动 `owner_id = user.id, scope='user'`，生成 `public_id = secrets.token_urlsafe(9)[:12]`（约 71 位熵）
- admin 可显式传 `scope='system'` 创建共享群组（供全员参考）
- 返回 `GroupOut`（含 `public_id`，**不含** integer `id`）

**E.3 GET /api/groups/{public_id}**
- 不可见 → 404（不暴露存在性，避免枚举）
- 用 `resolve_group(session, public_id)` 替换原 integer PK 查询

**E.4 PATCH /api/groups/{public_id}** — 新增（之前缺失）
- 仅 owner 或 admin 可改

**E.5 DELETE /api/groups/{public_id}**
- 仅 owner 或 admin 可删
- scope=system 不可删（admin 也不能硬删共享群组）

**E.6 runs / messages 透明跟随**

由于 `runs.group_id` 和 `messages.group_id` 都通过 group 间接归属 owner，list 接口都先做 group 可见性校验（用同样的 helper）：

```python
async def visible_group_ids(session, user) -> set[int]:
    """admin 拿全集；user 拿 system + 自己 owner 的群组"""
    if user.role == "admin":
        return None  # 无限制
    q = select(Group.id).where((Group.scope == "system") | (Group.owner_id == user.id))
    return {row[0] for row in (await session.execute(q)).all()}
```

- [api/runs.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/runs.py) `list_runs(group_id)` 校验 `group_id` 在可见集合内，否则 404
- [api/messages.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/messages.py) `list_messages(group_id)` 同上
- [api/chat.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/chat.py) `POST /chat` 提交 `group_id` 时同样校验；**body 字段名从 `group_id` 改成 `group_public_id`**（防止 integer id 出现在 wire 上）
- [api/attachments.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/attachments.py) `list_attachments` 的查询参数同步改成 `group_public_id`
- 所有调用方（前端 lib/api.ts、orchestrator/runner.py 的 start_run）同步切换

**E.9 chat / runs / messages 等需要 `group_public_id` 的 body 字段**

- `ChatRequest` schema：`group_id` 改名为 `group_public_id`，类型 `str` (≤16 字符)
- `RunCreate.group_id` 同上
- `listMessages(group_public_id)` 同上
- `listRuns(group_public_id)` 同上
- 后端内部在路由入口先把 `public_id` → 整数 id，再用整数 id 做 `group_members` / `runs` / `messages` / `attachments` 的 SQL join
- 整数 id **绝不**进 wire 出参；`GroupOut` 不含 `id` 字段，仅 `public_id` / `owner_id` / `scope`

**E.7 Group 模型字段**

```python
class Group(Base):
    __tablename__ = "groups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # 内部 PK，不出 wire
    public_id: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)  # URL/API 用
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(16), default="auto", nullable=False)
    max_rounds: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    scope: Mapped[str] = mapped_column(String(16), default="user", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

**E.8 GroupCard / GroupWizard / 首页**
- GroupCard 加 scope 标签（系统共享 / 我的）
- 删除按钮对非 owner 普通用户禁用
- "创建群组"对所有登录用户开放

### G. 审计日志集成点

把所有现有写操作 API 接入审计日志（最少 12 个端点）：

| 文件 | 端点 | action 命名 |
|---|---|---|
| [api/auth.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/auth.py) | POST /login | `auth.login` |
| | POST /login (失败) | `auth.login.fail` |
| | POST /logout | `auth.logout` |
| | POST /register | `auth.register` |
| [api/users.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/users.py) | 全部 | `user.create/update/delete/enable/reset_password` |
| [api/bots.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/bots.py) | 全部 | `bot.create/update/delete/set_skills` |
| [api/groups.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/groups.py) | 全部 | `group.create/update/delete/add_member/remove_member` |
| [api/skills.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/skills.py) | 全部 | `skill.create/update/delete/install_community/upload_asset` |
| [api/chat.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/chat.py) | POST /chat | `chat.run` |
| [api/runs.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/runs.py) | DELETE | `run.delete` |

每个端点执行 `await audit.log(...)` 后再 commit；失败时 status='failure', detail 包含异常 message + traceback 前 200 字符。

### H. 审计日志 API — 新文件 [app/api/audit.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/audit.py)

| Method | Path | 权限 | 行为 |
|---|---|---|---|
| GET  | `/api/audit/logs` | admin | 多维查询：?actor_id=&action=&target_type=&target_id=&from=&to=&page=&page_size= |
| GET  | `/api/audit/logs/{id}` | admin | 单条详情 |
| GET  | `/api/audit/stats` | admin | 聚合：最近 24h 各 action 计数、按用户 Top 10 |
| POST | `/api/audit/cleanup` | admin | 手动触发清理（返回删除条数） |

分页：cursor-based（id desc），page_size 默认 50，最大 500。

### I. 前端

**G.1 用户管理页** — 新文件 [frontend/app/admin/users/page.tsx](file:///root/Documents/trae_projects/botgroup/frontend/app/admin/users/page.tsx)

只对 admin 可见（fetch `/api/users` 失败 403 时显示无权限）。表格列：头像 / username / display_name / email / role / status / 最后登录 / 创建时间 / 操作（重置密码/启停/删除）。新增用户弹窗：表单（username + display_name + email + role + 初始密码可手填或自动生成）。

**G.2 审计日志页** — 新文件 [frontend/app/admin/audit/page.tsx](file:///root/Documents/trae_projects/botgroup/frontend/app/admin/audit/page.tsx)

顶栏：时间范围（最近 24h/7d/30d/自定义）+ 操作类型下拉 + 用户搜索 + target_type 下拉 + 「查询」按钮。
主体：日志表格（occurred_at / actor / action / target_type+id / status / ip）。点击单行展开 `detail` JSON 折叠面板。
分页：底部「上一页/下一页 + 总数」。

**G.3 Sidebar** — [frontend/components/Sidebar.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/Sidebar.tsx)

加一个 `isAdmin` 判断（从 `/api/users/me` 的 role 字段，或新增 `/api/auth/me` 顺便返回 role）：
- admin → 显示「🛡 管理」分组下：「用户管理」、「审计日志」
- 普通用户 → 隐藏整个管理分组

**G.4 BotCard / BotFormDialog / GroupWizard**：
- BotCard 增加 owner 标签 + scope 标签 + 锁定按钮（受保护 → `display_name` 不可改）
- GroupWizard 的 `availableBots` 由 `GET /api/bots` 服务端过滤后，前端直接用
- 删除按钮对非 owner/非 admin 禁用
- **所有跳转 URL 改用 `g.public_id`**：`router.push(\`/group/${g.public_id}\`)`、`GroupCard.tsx:38` `href={\`/group/${group.public_id}\`}`、`/group/[id]/page.tsx` 通过 `useParams()` 拿到 `public_id` 再调 `api.getGroup(public_id)`
- `listMessages` / `listRuns` 等函数签名改成传 `group_public_id`（字符串）

**G.5 api.ts 扩展** — [frontend/lib/api.ts](file:///root/Documents/trae_projects/botgroup/frontend/lib/api.ts)

- `User` 类型扩展 role/status/display_name/last_login_at
- `Bot` 类型加 owner_id/scope
- `Group` 类型：去掉 integer `id` 字段（不再对外暴露），改用 `public_id`
- `api.listUsers / createUser / updateUser / resetUserPassword / enableUser / disableUser / deleteUser`
- `api.listAuditLogs(params) / getAuditLog(id) / getAuditStats`
- `api.me()` 已存在但响应结构变化 → 需要更新 `MeOut` 在后端包含 role/display_name

## 假设与决策

1. **不引入新表 roles / permissions**，全部用 enum（admin/user）+ 业务判断，符合 YAGNI；如未来要更细粒度再加。
2. **审计日志不进业务事务**：写失败不让主操作回滚；fire-and-forget + retry-on-next-call。
3. **软删除用户**：disabled 后禁止登录、不能创建 bot，但历史消息与 bot 归属保留可追溯。admin 仍可见其创建的 bot（所有权不变）。
4. **bot 软删 or 硬删**：保持现有硬删（用户说「现有机器人设为系统默认」），但 scope=system 不可删；scope=user 的 bot 由 owner/admin 硬删。
5. **多管理员场景**：允许 >=1 个 admin；保留「最后一个 admin」保护（自我降级/删除/禁用都被拒绝）。
6. **日志清理策略**：每次启动 lifespan 跑一次；运行期间每天 0 点（croniter）再跑一次。retention 默认 90 天，可在 settings 里覆盖。
7. **IP/User-Agent 抓取**：用 `request.client.host` 与 `request.headers.get('user-agent')`；nginx 反代场景由 `X-Forwarded-For` 兜底（fastapi 已自动处理）。
8. **前端路由 `/admin/*` 不做额外鉴权**：依靠后端 401/403；前端兜底显示无权限空状态。
9. **登录失败也算审计**：避免暴力破解不可见，但同一 IP 短时间内多次失败仅记录一次（避免写爆），按 5 分钟窗口聚合。

## 验证步骤

实施完成后跑下列检查：

1. **迁移**：`docker compose exec backend alembic upgrade head` 应成功；`alembic downgrade -1` 然后再 upgrade 应可重放。
2. **后端 smoke**：
   ```bash
   # admin login
   curl -c /tmp/c.txt -X POST localhost:8000/api/auth/login -d '{"username":"admin","password":"admin"}' -H "content-type: application/json"
   # admin list users
   curl -b /tmp/c.txt localhost:8000/api/users
   # admin create user
   curl -b /tmp/c.txt -X POST localhost:8000/api/users -d '{"username":"alice","password":"alice12345","role":"user"}' -H "content-type: application/json"
   # user login
   curl -c /tmp/u.txt -X POST localhost:8000/api/auth/login -d '{"username":"alice","password":"alice12345"}' -H "content-type: application/json"
   # user cannot list users (403)
   curl -b /tmp/u.txt localhost:8000/api/users -o /dev/null -w "%{http_code}\n"   # 期望 403
   # user can list bots (只看到 system + 自己)
   curl -b /tmp/u.txt localhost:8000/api/bots
   # user create bot
   curl -b /tmp/u.txt -X POST localhost:8000/api/bots -d '{"name":"my-bot","model":"gpt-4o"}' -H "content-type: application/json"
   # user create group
   curl -b /tmp/u.txt -X POST localhost:8000/api/groups -d '{"name":"alice-private","bot_ids":[]}' -H "content-type: application/json"
   # admin 创建 bob 并登录
   curl -b /tmp/c.txt -X POST localhost:8000/api/users -d '{"username":"bob","password":"bob12345","role":"user"}' -H "content-type: application/json"
   curl -c /tmp/b.txt -X POST localhost:8000/api/auth/login -d '{"username":"bob","password":"bob12345"}' -H "content-type: application/json"
   # bob 看不到 alice 的群组 (404)
   curl -b /tmp/b.txt localhost:8000/api/groups/2 -o /dev/null -w "%{http_code}\n"   # 期望 404
   # admin 看得到 alice 的群组 (200)
   curl -b /tmp/c.txt localhost:8000/api/groups/2 -o /dev/null -w "%{http_code}\n"   # 期望 200
   # audit logs
   curl -b /tmp/c.txt "localhost:8000/api/audit/logs?action=auth.login&from=2026-01-01"
   ```
3. **前端 E2E（手动）**：
   - 浏览器登录 admin → sidebar 出现「用户管理」「审计日志」入口
   - 进入用户管理 → 新增 alice → 重置 alice 密码 → 启用/禁用 → 删除
   - 切到 alice 登录 → sidebar 不显示管理入口
   - alice 创建 bot「my-bot」→ bob 登录看不到这个 bot
   - admin 创建 system bot → 所有用户能看到但不能改
   - **alice 创建群组「alice 私聊」→ bob 登录看不到这个群组**；admin 登录能看到全部
   - **alice 进入聊天 → 历史任务列表只显示「alice 私聊」下的话题**；切换 bob 也类似
   - admin 把 alice 的群组 scope 提升为 system → 所有人可见
   - 审计日志页查 `user.create` / `bot.create` / `auth.login` / `group.create` 全部命中
4. **回归**：确认现有页面（首页群组 / 技能中心 / 聊天）行为不变。
5. **构建**：`docker compose build backend frontend` + `docker compose up -d` 应无报错。

## 涉及文件

### 新建
- [0013_rbac_and_audit.py](file:///root/Documents/trae_projects/botgroup/backend/alembic/versions/0013_rbac_and_audit.py)
- [app/services/audit.py](file:///root/Documents/trae_projects/botgroup/backend/app/services/audit.py)
- [app/api/users.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/users.py)
- [app/api/audit.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/audit.py)
- [frontend/app/admin/users/page.tsx](file:///root/Documents/trae_projects/botgroup/frontend/app/admin/users/page.tsx)
- [frontend/app/admin/audit/page.tsx](file:///root/Documents/trae_projects/botgroup/frontend/app/admin/audit/page.tsx)
- [frontend/components/admin/UsersTable.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/admin/UsersTable.tsx)
- [frontend/components/admin/AuditTable.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/admin/AuditTable.tsx)

### 修改
- [backend/app/db/models.py](file:///root/Documents/trae_projects/botgroup/backend/app/db/models.py) — User/Bot/Group/AuditLog 四处
- [backend/app/auth.py](file:///root/Documents/trae_projects/botgroup/backend/app/auth.py) — require_admin
- [backend/app/main.py](file:///root/Documents/trae_projects/botgroup/backend/app/main.py) — lifespan 启动清理 + 路由注册
- [backend/app/api/auth.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/auth.py) — MeOut 加 role / 登录接入审计
- [backend/app/api/bots.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/bots.py) — owner/scope 校验 + 审计
- [backend/app/api/groups.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/groups.py) — 审计
- [backend/app/api/skills.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/skills.py) — 审计
- [backend/app/api/chat.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/chat.py) — 审计
- [backend/app/api/runs.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/runs.py) — 审计
- [backend/app/schemas.py](file:///root/Documents/trae_projects/botgroup/backend/app/schemas.py) — UserOut/UserCreate/UserUpdate 等
- [backend/app/config.py](file:///root/Documents/trae_projects/botgroup/backend/app/config.py) — audit_retention_days
- [frontend/app/bots/page.tsx](file:///root/Documents/trae_projects/botgroup/frontend/app/bots/page.tsx) — 过滤可用 bot / 标签
- [frontend/app/page.tsx](file:///root/Documents/trae_projects/botgroup/frontend/app/page.tsx) — GroupWizard 适配
- [frontend/components/BotCard.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/BotCard.tsx) — owner/scope 标签
- [frontend/components/BotFormDialog.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/BotFormDialog.tsx) — system bot 锁定
- [frontend/components/GroupWizard.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/GroupWizard.tsx) — availableBots 过滤
- [frontend/components/Sidebar.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/Sidebar.tsx) — admin 分组入口
- [frontend/lib/api.ts](file:///root/Documents/trae_projects/botgroup/frontend/lib/api.ts) — User/Bot 类型扩展 + 新方法