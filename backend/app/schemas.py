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
    pass


class BotUpdate(BaseModel):
    name: str | None = None
    avatar_url: str | None = None
    emoji: str | None = Field(default=None, max_length=8)
    persona: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    params: dict[str, Any] | None = None
    # is_system is intentionally NOT updatable here — system identity is
    # seeded by the DB migration and can only be flipped via SQL.


class BotOut(BotBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_system: bool = False
    is_protected: bool = False
    created_at: datetime


class GroupBase(BaseModel):
    name: str
    description: str | None = None
    mode: str = Field(default="auto", pattern="^(round_robin|auto|manual)$")
    max_rounds: int = Field(default=6, ge=1, le=50)


class GroupCreate(GroupBase):
    bot_ids: list[int] = Field(default_factory=list)


class GroupOut(GroupBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    bot_ids: list[int] = Field(default_factory=list)


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    run_id: int | None
    group_id: int
    role: str
    bot_id: int | None
    content: str
    token_usage: int
    # IDs of bot-authored attachments surfaced by this message. The UI
    # renders a download button per ID; backend serves the bytes from
    # `GET /api/attachments/{id}/download`.
    attachments: list[int] = []
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

    group_id: int
    title: str | None = Field(default=None, max_length=128)


class RunUpdate(BaseModel):
    """Body for PATCH /api/tasks/{id} — currently only the title is
    user-editable. Status / counts / timestamps are server-managed."""

    title: str | None = Field(default=None, max_length=128)


class ChatRequest(BaseModel):
    group_id: int
    prompt: str
    max_rounds: int | None = None
    mode: str | None = Field(default=None, pattern="^(round_robin|auto|manual)$")
    # IDs of attachments (already parsed by MinerU) to inject as extra
    # context for this run. Each bot sees the concatenated Markdown in its
    # first user message.
    attachment_ids: list[int] | None = None
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