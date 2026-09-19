"""平台群规（防火墙规则）+ 群级群通知

两张改动：

1. 新建 `system_policies` 单行表（id 恒为 1），存放平台级「群规 /
   防火墙规则」：`enabled` 总开关 + `rules` JSON 数组。所有群组的所有
   bot、所有轮次都会在 system prompt 最前段注入这里的规则，且不可被
   用户指令或群级规则覆盖。

2. 给 `groups` 加 `notice` 列（Text，默认空串），存放群级追加的
   「群通知 / 群规」。注入时始终排在平台规则之后，作为补充而非覆盖。

不 seed 数据：无行时语义等价于「未配置规则」（不注入任何内容），
第一条 PUT 时由应用层 upsert 插入，因此无需改 main.py 的 lifespan。

向后兼容：`notice` 有 server_default，存量群自动为空串，行为与改动前
完全一致。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0018_group_policy"
down_revision: Union[str, None] = "0017_message_cited_refs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "rules",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "updated_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.add_column(
        "groups",
        sa.Column(
            "notice",
            sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
        ),
    )


def downgrade() -> None:
    op.drop_column("groups", "notice")
    op.drop_table("system_policies")
