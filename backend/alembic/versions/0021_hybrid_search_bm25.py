"""hybrid search — add tsvector + GIN index on kb_chunks.text.

Stage 1: this migration adds a `tsv` column (GENERATED ALWAYS AS
``to_tsvector('simple', text)`` STORED) and a GIN index on it, so
``local_retriever.retrieve`` can run a Postgres full-text-search
leg in parallel with the existing dense (pgvector cosine) leg.
Reciprocal Rank Fusion merges the two ranked lists; the dense path
is unchanged.

Why ``simple`` config:
  * Ships with every Postgres install — no extension required.
  * Splits on whitespace + lowercases + strips default punctuation.
  * Acceptable for the corpus we currently see (legal / insurance
    PDFs in mixed EN/CN). CJK is matched at the unigram level, which
    is fine for short tokens like ``SPC``, ``Treaty``, ``¶``.
  * If a future deployment reports poor Chinese-only recall, swap
    the text-search config to ``'public.chinese_zh''`` (requires the
    ``zhparser`` extension) or migrate to ``pg_trgm`` for n-gram
    matching. The query interface stays unchanged.

Why GENERATED … STORED:
  * Postgres rebuilds the column on every ``text`` UPDATE, so the
    application layer never has to maintain ``tsv`` explicitly.
  * Indexes on generated columns are allowed in PG 12+.

Why GIN, not GiST:
  * GIN is the standard recommendation for ``tsvector`` lookup-heavy
    workloads. Build is slower and writes are more expensive, but our
    corpus is append-mostly (one rebuild per ingested document).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0021_hybrid_search_bm25"
down_revision: Union[str, None] = "0020_kb_public_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: add the column as nullable TEXT — the GENERATED type
    # cast below will rewrite it as tsvector.
    op.add_column(
        "kb_chunks",
        sa.Column("tsv", sa.Text(), nullable=True),
    )
    # Step 2: rewrite to tsvector via GENERATED STORED. We backfill the
    # tsvector for *every existing row* in one ALTER. With ~5K chunks
    # × 160 chars this is well under a second.
    op.execute(
        "ALTER TABLE kb_chunks "
        "ALTER COLUMN tsv TYPE tsvector "
        "USING to_tsvector('simple', coalesce(text, ''))"
    )
    op.execute(
        "ALTER TABLE kb_chunks "
        "ALTER COLUMN tsv SET NOT NULL"
    )
    # Step 3: GIN index — the standard pick for tsvector.
    op.create_index(
        "ix_kb_chunks_tsv",
        "kb_chunks",
        ["tsv"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_kb_chunks_tsv", table_name="kb_chunks")
    op.drop_column("kb_chunks", "tsv")