"""add attachments.public_id — 用随机 token 取代自增 id 作为下载/外露 URL

原来 29 张 url 用的是整数自增 id (e.g. /api/attachments/123/download),
任何已认证用户都可以顺次推 123, 124, ... 下载附件。换成 24 字节 url-safe
随机 token 后, 链接不可枚举, 不暴露附件总数。
"""
from typing import Sequence, Union

import secrets

from alembic import op
import sqlalchemy as sa


revision: str = "0015_attachment_public_id"
down_revision: Union[str, None] = "0014_bot_is_public"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _new_token() -> str:
    # 24 字节 = 192 位熵, url-safe base64 编码后约 32 字符。远超 128 位安全阈值。
    return secrets.token_urlsafe(24)


def upgrade() -> None:
    # 先加可空列, 把所有现存行回填一个随机 token, 然后改为 NOT NULL + 加唯一索引。
    op.add_column(
        "attachments",
        sa.Column("public_id", sa.String(length=48), nullable=True),
    )

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id FROM attachments")).fetchall()
    for (pk,) in rows:
        # 极小概率碰撞 (192 位熵) — 真撞了就重试一次
        for _ in range(5):
            token = _new_token()
            try:
                bind.execute(
                    sa.text("UPDATE attachments SET public_id = :t WHERE id = :i"),
                    {"t": token, "i": pk},
                )
                break
            except Exception:
                continue

    op.alter_column("attachments", "public_id", nullable=False)
    op.create_index(
        "ix_attachments_public_id", "attachments", ["public_id"], unique=True
    )

    # Backfill the `messages.attachments` JSON column: each entry is a
    # bot-authored attachment reference. The old format was a list of
    # integer ids (e.g. [47, 48]); the new format is a list of public_id
    # tokens (e.g. ["ociwRrutmF...", "bvQFCNGqBL..."]). Walk every
    # message row, swap integer ids for the matching attachment's new
    # public_id, and skip anything that doesn't resolve (the attachment
    # may have been deleted since the message was written).
    # Backfill the `messages.attachments` JSON column: each entry is a
    # bot-authored attachment reference. The old format was a list of
    # integer ids (e.g. [47, 48]); the new format is a list of public_id
    # tokens (e.g. ["ociwRrutmF...", "bvQFCNGqBL..."]). Walk every
    # message row, swap integer ids for the matching attachment's new
    # public_id, and skip anything that doesn't resolve (the attachment
    # may have been deleted since the message was written).
    #
    # NOTE: messages.attachments is stored as JSON, not JSONB. The
    # jsonb_* helpers below still work because Postgres implicitly
    # casts json → jsonb when calling a jsonb-returning function.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, attachments FROM messages "
            "WHERE attachments IS NOT NULL "
            "  AND attachments::text NOT IN ('null', '[]')"
        )
    ).fetchall()
    updated = 0
    for msg_id, raw in rows:
        new_raw = bind.execute(
            sa.text(
                """
                SELECT jsonb_agg(
                    CASE
                        WHEN jsonb_typeof(elem) = 'number'
                            THEN to_jsonb(a.public_id)
                        ELSE elem
                    END
                ) FILTER (
                    WHERE NOT (jsonb_typeof(elem) = 'number' AND a.public_id IS NULL)
                ) AS new_attachments
                FROM jsonb_array_elements(CAST(:raw AS jsonb)) AS elem
                LEFT JOIN attachments a ON a.id = (elem #>> '{}')::int
                """
            ),
            {"raw": raw},
        ).scalar()
        if new_raw and new_raw != raw:
            bind.execute(
                sa.text("UPDATE messages SET attachments = :a WHERE id = :i"),
                {"a": new_raw, "i": msg_id},
            )
            updated += 1


def downgrade() -> None:
    op.drop_index("ix_attachments_public_id", table_name="attachments")
    op.drop_column("attachments", "public_id")