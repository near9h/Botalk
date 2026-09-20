"""knowledge_bases.public_id — wire-facing unguessable KB identifier.

Mirrors the same shift we did for groups and attachments: the integer
`knowledge_bases.id` is no longer used on the wire. Routes that take a
KB now resolve via `public_id` so URLs can't be enumerated by
probing `/knowledge/1`, `/knowledge/2`, ...

We backfill existing rows with `secrets.token_urlsafe(16)` — same
length scheme used elsewhere — and add a unique index. New rows get
their token in the application layer (`api/kb.py.create_kb`).

Downgrade drops the column. Other tables reference `kb_id` (integer),
which is left alone — the integer stays as the internal FK target.
"""
from typing import Sequence, Union

import secrets

from alembic import op
import sqlalchemy as sa


revision: str = "0020_kb_public_id"
down_revision: Union[str, None] = "0019_local_vector_retrieval"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column("public_id", sa.String(64), nullable=True),
    )
    # Backfill existing rows with a fresh token each. We can't use
    # `gen_random_uuid()` because the pgvector image's pg doesn't
    # ship pgcrypto by default. Instead, fetch the rows and update
    # them one by one from Python — the table is tiny (one row per
    # KB owner) so this is cheap.
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id FROM knowledge_bases")).all()
    for (kb_id,) in rows:
        bind.execute(
            sa.text("UPDATE knowledge_bases SET public_id = :pid WHERE id = :id"),
            {"pid": secrets.token_urlsafe(16), "id": kb_id},
        )
    op.alter_column("knowledge_bases", "public_id", nullable=False)
    op.create_index(
        "uq_kb_public_id",
        "knowledge_bases",
        ["public_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_kb_public_id", table_name="knowledge_bases")
    op.drop_column("knowledge_bases", "public_id")
