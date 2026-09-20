"""local-vector retrieval — kb_chunks carries the chunk text + embedding.

Before this migration the KB pipeline relied on RAGFlow as the vector
store: chunks were uploaded there and `kb_chunks.ragflow_chunk_id`
indexed a mirrored copy of the metadata. Retrieval happened over HTTP
against RAGFlow, never against Postgres.

The environment hosting BotGroup can't run RAGFlow (≥4C8G + ES), so
this migration switches the storage to Postgres + pgvector and rewires
the retrieval path. Per-chunk payload is now self-contained:

* `kb_chunks.text` — full chunk text (used for LLM context; the old
  schema only kept a 200-char snippet because the rest lived in
  RAGFlow). Long enough to keep the model informed, short enough not
  to bloat rows: capped at 4000 chars per chunk.
* `kb_chunks.embedding` — pgvector `vector(N)` column where N matches
  `settings.zhipuai_embedding_dim` (1024 for `embedding-3`). Populated
  by the ingest worker on every new chunk.
* `kb_chunks.embedding_model` — model id baked into the vector. We
  refuse to mix different model embeddings in one column (cosine
  similarity across them is meaningless), and the worker reads it back
  to detect migrations.

The 1024-dim default is hard-coded for now. When the operator switches
embedding models, run a follow-up re-index migration.

Downgrade drops the columns. The rest of the schema (kb_documents,
kb_chunks.ragflow_chunk_id, knowledge_bases.ragflow_dataset_id) is
kept so a future RAGFlow restoration is non-destructive.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0019_local_vector_retrieval"
down_revision: Union[str, None] = "0018_group_policy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# GLM `embedding-3` returns 2048-dim vectors; pgvector needs the dim
# in the column type so the operator can ALTER it on model switches.
# Note: pgvector's HNSW/IVFFlat indexes cap at 2000 dims, so we
# deliberately don't create an ANN index here — see app config
# comment for the workarounds.
EMBEDDING_DIM = 2048


def upgrade() -> None:
    # Enable pgvector. The `pgvector/pgvector:pg16` image already ships
    # the shared library; CREATE EXTENSION just registers it in the DB.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Reasonable initial size for the text column. PDFs regularly yield
    # paragraphs of 800-2000 chars; this gives enough room without
    # bloating index size on a per-row basis.
    op.add_column(
        "kb_chunks",
        sa.Column("text", sa.Text, nullable=False, server_default=""),
    )
    # Backfill `text` from the existing snippet so the upgrade is
    # non-destructive on rows already in the table. New rows will get
    # the full text from the ingest worker.
    op.execute("UPDATE kb_chunks SET text = snippet WHERE text = ''")

    op.add_column(
        "kb_chunks",
        sa.Column(
            "embedding",
            sa.String(64).with_variant(
                # SQLAlchemy `String` placeholder; we replace with the
                # real pgvector type below via raw DDL because there's
                # no first-class SQLAlchemy pgvector type in our
                # dependency set.
                sa.String(64),
                "postgresql",
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "kb_chunks",
        sa.Column("embedding_model", sa.String(64), nullable=True),
    )

    # Convert the placeholder column into a pgvector type. Doing this
    # in raw SQL avoids dragging the pgvector SQLAlchemy package in as
    # a dependency just for one column type.
    op.execute(
        f"ALTER TABLE kb_chunks "
        f"ALTER COLUMN embedding TYPE vector({EMBEDDING_DIM}) "
        f"USING NULL"
    )

    # Note: pgvector's HNSW / IVFFlat indexes cap at 2000 dimensions;
    # GLM embedding-3 returns 2048-dim vectors so we run an exact
    # ORDER BY distance LIMIT N instead. Once the KB grows past ~10k
    # chunks we'll either downgrade the model or pre-truncate to
    # 1536 dims before storage; at that point a follow-up migration
    # can add the index.
    # (Earlier versions of this migration tried to add an HNSW index
    # — that fails with the current dim, hence the empty block.)

    op.add_column(
        "kb_documents",
        sa.Column(
            "embedding_model",
            sa.String(64),
            nullable=True,
        ),
    )


def downgrade() -> None:
    # No index was created (HNSW/IVFFlat both cap at 2000-dim).
    op.drop_column("kb_documents", "embedding_model")
    op.drop_column("kb_chunks", "embedding_model")
    op.drop_column("kb_chunks", "embedding")
    op.drop_column("kb_chunks", "text")
    # Note: we don't `DROP EXTENSION vector` on downgrade — other
    # tables (or future migrations) may depend on it.
