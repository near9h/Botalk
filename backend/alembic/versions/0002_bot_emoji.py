"""add emoji to bots

Revision ID: 0002_bot_emoji
Revises: 0001_initial
Create Date: 2026-09-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_bot_emoji"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bots",
        sa.Column(
            "emoji",
            sa.String(8),
            nullable=False,
            server_default="\U0001F916",  # 🤖
        ),
    )


def downgrade() -> None:
    op.drop_column("bots", "emoji")