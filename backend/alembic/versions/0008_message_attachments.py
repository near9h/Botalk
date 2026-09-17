"""add messages.attachments (JSONB) to carry bot-authored file references.

When a bot writes a long document, it wraps the output in
[FILE:filename.md]...[/FILE] blocks; the orchestrator splits these out and
creates Attachment rows + adds their IDs to the message's `attachments`
column so the UI can render download buttons.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008_message_attachments"
down_revision: Union[str, None] = "0007_skills"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "attachments",
            sa.JSON,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "attachments")