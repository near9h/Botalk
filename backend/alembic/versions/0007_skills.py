"""add skills + bot_skills tables

Revision ID: 0007_skills
Revises: 0006_widen_mime
Create Date: 2026-09-17

Built-in skills are NOT seeded here — they are upserted idempotently at app
startup by `app.skills.registry.ensure_builtin_skills` so the manifest /
config_schema JSON stays maintainable in code rather than SQL string literals.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_skills"
down_revision: Union[str, None] = "0006_widen_mime"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("key", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("category", sa.String(32), nullable=False, server_default="custom"),
        sa.Column("icon", sa.String(8), nullable=False, server_default="🧩"),
        sa.Column("manifest", sa.JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("config_schema", sa.JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("builtin", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "bot_skills",
        sa.Column(
            "bot_id",
            sa.Integer,
            sa.ForeignKey("bots.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "skill_id",
            sa.Integer,
            sa.ForeignKey("skills.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("config", sa.JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("bot_skills")
    op.drop_table("skills")
