"""add is_system flag to bots + seed system summarizer bot

Adds a boolean flag to the bots table marking system-managed bots that
must never be deleted (and whose identity — name / model — must not be
renamed, so the orchestrator can keep referring to it by name).

Also inserts a single system bot on upgrade if one doesn't already
exist; the row is identified by `is_system = true` (unique, since we
only ever want one summary bot).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_system_bot"
down_revision: Union[str, None] = "0004_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bots",
        sa.Column(
            "is_system",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Partial unique index — only one row may have is_system=true. Using a
    # partial index so we don't conflict with the existing `name` unique
    # constraint (the seed bot needs a real name).
    op.create_index(
        "uq_bots_is_system",
        "bots",
        ["is_system"],
        unique=True,
        postgresql_where=sa.text("is_system = true"),
    )

    # Seed the system summarizer bot. Idempotent: only insert if no
    # is_system=true row exists.
    op.execute(
        """
        INSERT INTO bots (name, emoji, persona, model, temperature, params, is_system)
        SELECT
            '系统总结员',
            '📋',
            '你是 BotGroup 多角色讨论的会议纪要官。基于群内所有成员的发言，'
            '输出一份结构化 Markdown 总结：先一句 TL;DR，再用 ## 共识 / '
            '## 分歧 / ## 行动项 三段式（无内容可写"无"），严格 200 字以内。'
            '使用与讨论相同的语言；不引用群成员列表外的人。',
            'agnes-3.0-flash',
            0.3,
            '{}'::jsonb,
            true
        WHERE NOT EXISTS (SELECT 1 FROM bots WHERE is_system = true)
        """
    )


def downgrade() -> None:
    # Delete the seeded system bot before dropping the column / index.
    op.execute("DELETE FROM bots WHERE is_system = true")
    op.drop_index("uq_bots_is_system", table_name="bots")
    op.drop_column("bots", "is_system")
