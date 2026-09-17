"""add tasks.share_token (opaque random id for safe URL sharing)

A task's integer id leaks two pieces of information when it appears in
a shared URL:
  1. The total volume of tasks in this group (cumulative).
  2. The order tasks were created in (so a guesser can probe id+1, id-1
     to find adjacent threads).

This migration adds a 12-character base62 random token that replaces
the integer id in URLs (`/group/{gid}?task=<token>`). The integer id
stays as the DB primary key and as the message.run_id foreign key —
only the wire-facing lookup switches to the token.

The column is generated up-front for every existing task so existing
history links can still resolve (otherwise old tasks would 404 when
followed). New tasks get their token in app code at creation time.
"""
import secrets
import string
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012_task_share_token"
down_revision: Union[str, None] = "0011_task_concept"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 12 chars × log2(62) ≈ 71 bits of entropy. Plenty for a URL token
# that nobody should be iterating; not so long that the URL gets ugly.
_TOKEN_ALPHABET = string.ascii_letters + string.digits
_TOKEN_LENGTH = 12


def _gen_token() -> str:
    # secrets.choice is the CSPRNG-backed version of random.choice;
    # using secrets avoids the predictable sequence that random()
    # would produce in this script's process lifetime.
    return "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(_TOKEN_LENGTH))


def upgrade() -> None:
    # Add the column nullable first so the backfill below can populate
    # every existing row; then flip to NOT NULL + unique in the same
    # migration.
    op.add_column(
        "runs",
        sa.Column("share_token", sa.String(16), nullable=True),
    )

    # Backfill: one token per existing row. We do this in Python so we
    # can use the `secrets` module (the alembic op.execute SQL doesn't
    # have an easy portable way to generate CSPRNG strings across
    # sqlite/postgres without writing a plpgsql function).
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id FROM runs ORDER BY id")).fetchall()
    seen: set[str] = set()
    for (rid,) in rows:
        # Re-roll until we land on a token no other row has (extremely
        # unlikely given the entropy, but cheap to verify).
        while True:
            tok = _gen_token()
            if tok not in seen:
                seen.add(tok)
                break
        bind.execute(
            sa.text("UPDATE runs SET share_token = :tok WHERE id = :id"),
            {"tok": tok, "id": rid},
        )

    # Now that every row has a token, flip to NOT NULL + unique.
    op.alter_column("runs", "share_token", nullable=False)
    op.create_unique_constraint("uq_runs_share_token", "runs", ["share_token"])
    op.create_index("ix_runs_share_token", "runs", ["share_token"])


def downgrade() -> None:
    op.drop_index("ix_runs_share_token", table_name="runs")
    op.drop_constraint("uq_runs_share_token", "runs", type_="unique")
    op.drop_column("runs", "share_token")
