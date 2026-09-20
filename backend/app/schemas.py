"""Pydantic schemas."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, ConfigDict


class BotBase(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    avatar_url: str | None = None
    emoji: str = Field(default="\U0001F916", max_length=8)
    persona: str = ""
    model: str
    temperature: float = Field(default=0.7, ge=0, le=2)
    params: dict[str, Any] = Field(default_factory=dict)


class BotCreate(BotBase):
    # admin 显式传 scope='system' 创建系统共享 bot；普通用户忽略此字段，强制 'user'
    scope: str | None = Field(default=None, pattern="^(system|user)$")
    # 创建时直接标记为公开；只对 owner 生效（system bot 由 migration 控制）
    is_public: bool = False


class BotUpdate(BaseModel):
    name: str | None = None
    avatar_url: str | None = None
    emoji: str | None = Field(default=None, max_length=8)
    persona: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    params: dict[str, Any] | None = None
    # 公开分享：owner 可设为 true 把私有 bot 分享给所有用户可见（但只有 owner/admin 能改/删）
    is_public: bool | None = None
    # 知识库挂载：传一个完整 list 覆盖（idempotent：缺失的 unbind，多出的 bind）。
    # 留 None 表示不动；传 [] 表示解绑所有。
    #
    # 列表里是 wire-facing `public_id` token 而不是整数 PK，与
    # `KnowledgeBase.public_id` 一致。
    kb_public_ids: list[str] | None = None
    # is_system / is_protected / scope / owner_id 不可通过 PATCH 改；只能由 admin
    # 通过独立的"提升/降级"接口或 SQL 改。
    # is_system is intentionally NOT updatable here — system identity is
    # seeded by the DB migration and can only be flipped via SQL.


class BotOut(BotBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_system: bool = False
    is_protected: bool = False
    # RBAC 扩展
    owner_id: int | None = None
    scope: str = "user"
    is_public: bool = False
    # 知识库挂载 id 列表（前端编辑表单直接绑定）
    kb_ids: list[int] = []  # integer FKs — internal use only
    kb_public_ids: list[str] = []  # wire-facing tokens for the frontend
    created_at: datetime


class GroupBase(BaseModel):
    name: str
    description: str | None = None
    mode: str = Field(default="auto", pattern="^(round_robin|auto|manual)$")
    max_rounds: int = Field(default=6, ge=1, le=50)


class GroupCreate(GroupBase):
    bot_ids: list[int] = Field(default_factory=list)
    # admin 可显式传 scope='system' 创建共享群组；普通用户忽略，强制 'user'
    scope: str | None = Field(default=None, pattern="^(system|user)$")
    # 群级「群通知 / 群规」追加文本（创建时可选）。
    notice: str | None = Field(default=None, max_length=2000)


class GroupUpdate(BaseModel):
    """PATCH body for /api/groups/{public_id}. All fields optional."""

    name: str | None = Field(default=None, max_length=128)
    description: str | None = None
    mode: str | None = Field(default=None, pattern="^(round_robin|auto|manual)$")
    max_rounds: int | None = Field(default=None, ge=1, le=50)
    # 群级「群通知 / 群规」追加文本。仅 owner / admin 可改（沿用既有权限）。
    notice: str | None = Field(default=None, max_length=2000)


class GroupOut(GroupBase):
    model_config = ConfigDict(from_attributes=True)
    # 注意：这里**故意**没有 `id: int` 字段。整数 id 仅作内部主键，
    # wire 出参只暴露 public_id。
    public_id: str
    # RBAC 扩展
    owner_id: int | None = None
    # Resolved owner username for display. None when scope="system"
    # (no single human owner).
    owner_username: str | None = None
    scope: str = "user"
    # 群级「群通知 / 群规」，空串表示未配置。
    notice: str = ""
    created_at: datetime
    bot_ids: list[int] = Field(default_factory=list)


# ──────────────────── 平台群规 / 防火墙规则 ────────────────────


class PolicyRule(BaseModel):
    """单条平台群规。`id` 缺省时由服务端补一个短随机串。"""

    id: str | None = Field(default=None, max_length=32)
    title: str = Field(default="", max_length=60)
    content: str = Field(default="", max_length=800)
    enabled: bool = True


class PolicyUpdate(BaseModel):
    """PUT /api/policies 请求体 —— 整表替换。"""

    enabled: bool = True
    rules: list[PolicyRule] = Field(default_factory=list, max_length=50)


class PolicyOut(BaseModel):
    """GET/PUT /api/policies 响应。

    `preview` 是后端用同一套渲染逻辑算出的「平台群规段」文本，
    管理页直接展示它即可，无需在前端复刻渲染规则。
    """

    enabled: bool
    rules: list[PolicyRule] = Field(default_factory=list)
    preview: str | None = None
    updated_at: datetime | None = None
    updated_by_username: str | None = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    run_id: int | None
    group_id: int
    role: str
    bot_id: int | None
    content: str
    token_usage: int
    # public_ids of bot-authored attachments surfaced by this message. The
    # UI renders a download button per token; backend serves the bytes
    # from `GET /api/attachments/{public_id}/download`.
    attachments: list[str] = []
    # Stage 3: KB citation metadata persisted alongside the message so
    # /api/messages can re-render SourceCitation chips on refresh. Each
    # entry is a dict with chunk_id / kb_id / kb_doc_id / filename /
    # page / para / bbox / snippet / score / ragflow_chunk_id /
    # citation_key. Empty list when the bot had no KB mounted.
    cited_refs: list[dict] = []
    created_at: datetime


class RunOut(BaseModel):
    """A single discussion session (= a "task" in user-facing language).

    One user prompt triggers one task; the orchestrator may then have
    multiple bots reply before the task finishes. Every task is a
    self-contained thread the user can reopen from the history panel.
    """

    model_config = ConfigDict(from_attributes=True)
    id: int
    group_id: int
    status: str
    title: str = ""
    # Opaque random token for safe URL sharing. UI builds links as
    # `/group/{gid}?task=<share_token>` so the recipient pins to this
    # exact thread without seeing the internal integer id.
    share_token: str = ""
    started_at: datetime
    finished_at: datetime | None
    total_tokens: int
    user_prompt: str
    message_count: int = 0


class RunCreate(BaseModel):
    """Body for POST /api/tasks — opens a fresh empty task in a group."""

    group_public_id: str = Field(min_length=1, max_length=16)
    title: str | None = Field(default=None, max_length=128)


class RunUpdate(BaseModel):
    """Body for PATCH /api/tasks/{id} — currently only the title is
    user-editable. Status / counts / timestamps are server-managed."""

    title: str | None = Field(default=None, max_length=128)


class ChatRequest(BaseModel):
    group_public_id: str = Field(min_length=1, max_length=16)
    prompt: str
    max_rounds: int | None = None
    mode: str | None = Field(default=None, pattern="^(round_robin|auto|manual)$")
    # IDs of attachments (already parsed by MinerU) to inject as extra
    # context for this run. Each bot sees the concatenated Markdown in its
    # first user message.
    attachment_ids: list[str] | None = Field(
        default=None,
        description=(
            "Public ids (share_tokens) of attachments to inject as extra "
            "context. Frontend has been sending these strings since the "
            "HTTPS/share_token refactor (commit 600e658); backend "
            "resolves them to integer ids before querying."
        ),
    )
    # Optional: append this user message into an existing task instead of
    # creating a new one. Accepts either the integer id (legacy/internal)
    # or the share_token (preferred for URLs). When both are missing we
    # allocate a fresh task.
    task_id: int | None = None
    task_token: str | None = Field(default=None, max_length=16)


# ─────────────────────────── skills ───────────────────────────


class SkillBase(BaseModel):
    # `key` may be empty on create — the endpoint derives one from `name`.
    key: str = Field(default="", max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    type: str = Field(pattern="^(knowledge|tool|mcp)$")
    category: str = Field(default="custom", max_length=32)
    icon: str = Field(default="\U0001F9E9", max_length=8)
    manifest: dict[str, Any] = Field(default_factory=dict)
    config_schema: dict[str, Any] = Field(default_factory=dict)


class SkillCreate(SkillBase):
    pass


class SkillOut(SkillBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    builtin: bool = False
    created_at: datetime


class SkillImportMcp(BaseModel):
    url: str
    transport: str = Field(default="streamable-http", pattern="^(streamable-http|sse)$")
    name: str | None = None
    description: str | None = None


class SkillImportUrl(BaseModel):
    url: str
    name: str | None = None


class SkillAssetUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_default: bool | None = None


class BotSkillSet(BaseModel):
    skill_ids: list[int] = Field(default_factory=list)


class BotSkillOut(BaseModel):
    skill: SkillOut
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


# ─────────────────────── users (admin) ───────────────────────


class UserOut(BaseModel):
    """Returned by /api/users and /api/auth/me."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str | None = None
    email: str | None = None
    role: str
    status: str
    created_by_id: int | None = None
    last_login_at: datetime | None = None
    created_at: datetime


class UserCreate(BaseModel):
    """Admin-only. 创建用户，password 为空则由服务端生成 12 位随机密码并返回。"""

    username: str = Field(min_length=1, max_length=64)
    password: str | None = Field(default=None, min_length=8, max_length=256)
    display_name: str | None = Field(default=None, max_length=128)
    email: str | None = Field(default=None, max_length=256)
    role: str = Field(default="user", pattern="^(admin|user)$")


class UserResetPasswordOut(BaseModel):
    username: str
    new_password: str  # 仅生成时返回一次


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)
    email: str | None = Field(default=None, max_length=256)
    role: str | None = Field(default=None, pattern="^(admin|user)$")
    status: str | None = Field(default=None, pattern="^(active|disabled)$")


class UserChangePassword(BaseModel):
    """Self-service password change.

    The caller must be the user themselves (or an admin). `old_password`
    is required for self-service so a hijacker who only has the session
    cookie still can't rotate the password. Admins using this endpoint
    against a different user may pass `old_password=""` to skip the
    check (the admin-only `reset-password` endpoint is the right tool
    when you don't know the current password).
    """

    old_password: str = Field(default="", max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


# ─────────────────────── audit ───────────────────────


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    occurred_at: datetime
    actor_id: int | None = None
    actor_name: str
    actor_role: str
    action: str
    target_type: str
    target_id: str | None = None
    target_name: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    status: str
    detail: dict[str, Any] = Field(default_factory=dict)


class AuditLogsPage(BaseModel):
    items: list[AuditLogOut]
    total: int
    limit: int
    offset: int


class AuditCleanupResult(BaseModel):
    deleted: int
    retention_days: int