"""add bots.is_public — 允许 owner 把自己的 bot 公开给所有用户"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014_bot_is_public"
down_revision: Union[str, None] = "0013_rbac_and_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bots",
        sa.Column(
            "is_public",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index("ix_bots_is_public", "bots", ["is_public"])


def downgrade() -> None:
    op.drop_index("ix_bots_is_public", table_name="bots")
    op.drop_column("bots", "is_public")