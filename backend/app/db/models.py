"""SQLAlchemy ORM models."""
from datetime import datetime
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Bot(Base):
    __tablename__ = "bots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(512))
    emoji: Mapped[str] = mapped_column(String(8), default="\U0001F916", nullable=False)
    persona: Mapped[str] = mapped_column(Text, default="", nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    params: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # System-managed bots (e.g. the summarizer) can't be deleted and
    # can't have their identity (name/model) changed. Partial unique
    # index `uq_bots_is_system` enforces at most one such row.
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Soft-protection for product bots that the orchestrator relies on
    # (e.g. doc_writer / doc_auditor). UI hides destructive actions for
    # these bots. Distinct from `is_system`, which marks backend-managed
    # bots (like the summarizer) that never surface as editable cards.
    is_protected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(16), default="auto", nullable=False)
    max_rounds: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    members: Mapped[list["GroupMember"]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
        order_by="GroupMember.join_order",
    )


class GroupMember(Base):
    __tablename__ = "group_members"

    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    bot_id: Mapped[int] = mapped_column(
        ForeignKey("bots.id", ondelete="CASCADE"), primary_key=True
    )
    join_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    group: Mapped["Group"] = relationship(back_populates="members")
    bot: Mapped["Bot"] = relationship()


class Run(Base):
    """A "task" = one user turn + the multi-bot discussion it triggers.

    Conceptually a task is the unit the user navigates by in the chat
    UI: every task is a self-contained thread with its own message
    history. The table is called `runs` for historical reasons (it was
    originally just the orchestrator's run log); semantically it now
    doubles as the tasks table and the API aliases it as such.
    """

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # pending = created explicitly via "new task" but no user message yet
    # running = orchestrator is producing a reply
    # done    = orchestrator finished without error
    # error   = orchestrator failed
    # cancelled = user hit "stop" mid-stream
    status: Mapped[str] = mapped_column(String(16), default="running", nullable=False)
    # User-visible title. Defaults to the first 30 chars of user_prompt
    # but can be renamed via PATCH /api/tasks/{id}. Empty string means
    # "no user message yet" (a fresh pending task).
    title: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    user_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    # Materialized message count. The chat API bumps this on every
    # save_message call so /api/tasks list doesn't need a per-row count
    # query (which would dominate as messages accumulate).
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=True
    )
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    bot_id: Mapped[int | None] = mapped_column(
        ForeignKey("bots.id", ondelete="SET NULL"), nullable=True
    )
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    token_usage: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # List of attachment IDs that this message authored. When a bot reply
    # contains [FILE:foo.md]...[/FILE] blocks, the orchestrator splits
    # them out, creates Attachment rows, and appends their IDs here so
    # the UI can render download buttons.
    attachments: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Attachment(Base):
    """A user-uploaded file (PDF/…) that has been parsed by MinerU.

    `content_md` is the parsed Markdown used as extra context in chat rounds.
    `status` lets the UI show a progress bar while MinerU is working.
    """

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # When a bot *authors* an attachment (rather than the user uploading
    # one), `bot_id` records which bot wrote it and `source = "bot"` is
    # set. UI can render these as "下载报告" instead of the upload spinner.
    bot_id: Mapped[int | None] = mapped_column(
        ForeignKey("bots.id", ondelete="SET NULL"), nullable=True
    )
    # "user" | "bot" — lets the API & UI distinguish uploaded inputs from
    # bot-authored outputs (download buttons) without re-parsing context.
    source: Mapped[str] = mapped_column(String(8), default="user", nullable=False)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # pending | done | failed
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    err_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_md: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # raw file path on local disk (transient, may be cleaned up after parse)
    storage_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class User(Base):
    """A login user. Currently single-user is the default; multi-user could
    add an `is_admin` column and per-row policies later."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Skill(Base):
    """A reusable capability attachable to bots.

    Three kinds, distinguished by `type`:
      - `knowledge`: prompt/instructions + template assets (e.g. document writer)
      - `tool`:      built-in function-calling tools (search / crawl / chart)
      - `mcp`:       tools proxied from an external MCP server

    `manifest` holds type-specific definitions (instructions/assets for
    knowledge, OpenAI tool schemas for tool, url/transport/tool cache for mcp).
    `config_schema` describes the config knobs the UI should render (e.g.
    which API keys the tool needs), so the skill center can stay generic.
    """

    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)  # knowledge|tool|mcp
    category: Mapped[str] = mapped_column(
        String(32), default="custom", nullable=False
    )  # document|search|crawl|chart|mcp|custom
    icon: Mapped[str] = mapped_column(String(8), default="\U0001F9E9", nullable=False)
    # Use MutableDict so SQLAlchemy detects nested mutations on the
    # `assets` list / per-asset dicts (name, description, is_default).
    # Without it, `target[k] = v` inside the dict wouldn't trigger an
    # UPDATE on commit and the changes would silently disappear.
    manifest: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict, nullable=False)
    config_schema: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict, nullable=False)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BotSkill(Base):
    """Many-to-many join between a bot and its enabled skills, with a
    per-bot config override (e.g. a custom document template)."""

    __tablename__ = "bot_skills"

    bot_id: Mapped[int] = mapped_column(
        ForeignKey("bots.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[int] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True
    )
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    bot: Mapped["Bot"] = relationship()
    skill: Mapped["Skill"] = relationship()