"""widen attachments.mime_type from 64 to 128 chars

Standard Office MIME strings (e.g. the OpenXML family) are exactly 64
chars long, which means any extra charset parameter, whitespace, or a
browser-specific variant pushes the value past the limit and crashes
the INSERT with `value too long for type character varying(64)`. Going
to 128 gives plenty of headroom without bloating the row.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_widen_mime"
down_revision: Union[str, None] = "0005_system_bot"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "attachments",
        "mime_type",
        existing_type=sa.String(64),
        type_=sa.String(128),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Postgres will refuse to shrink a column if any existing row is
    # longer than the new limit. The seed/test data we ship fits in
    # 64, so this is safe in our environment; a real deployment might
    # need a cleanup pass first.
    op.alter_column(
        "attachments",
        "mime_type",
        existing_type=sa.String(128),
        type_=sa.String(64),
        existing_nullable=False,
    )
