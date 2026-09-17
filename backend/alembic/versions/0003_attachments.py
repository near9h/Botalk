"""add attachments table

Revision ID: 0003_attachments
Revises: 0002_bot_emoji
Create Date: 2026-09-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_attachments"
down_revision: Union[str, None] = "0002_bot_emoji"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "attachments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "group_id",
            sa.Integer,
            sa.ForeignKey("groups.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("filename", sa.String(256), nullable=False),
        sa.Column("mime_type", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("err_msg", sa.Text, nullable=True),
        sa.Column("content_md", sa.Text, nullable=False, server_default=""),
        sa.Column("storage_path", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_attachments_group_id", "attachments", ["group_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_attachments_group_id", table_name="attachments")
    op.drop_table("attachments")