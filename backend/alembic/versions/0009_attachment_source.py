"""add bot_id + source to attachments (track bot-authored file outputs).

When a bot reply contains a [FILE:foo.md]…[/FILE] block, the chat layer
now persists it as an Attachment row and links it to the message via
`messages.attachments`. We tag those rows with `source = "bot"` so the
UI can render a download button instead of treating them as a parsed
input, and we keep the original `source = "user"` default for uploads.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009_attachment_source"
down_revision: Union[str, None] = "0008_message_attachments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "attachments",
        sa.Column("bot_id", sa.Integer, nullable=True),
    )
    op.create_foreign_key(
        "attachments_bot_id_fkey",
        "attachments",
        "bots",
        ["bot_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "attachments",
        sa.Column(
            "source",
            sa.String(8),
            nullable=False,
            server_default=sa.text("'user'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("attachments", "source")
    op.drop_constraint("attachments_bot_id_fkey", "attachments", type_="foreignkey")
    op.drop_column("attachments", "bot_id")