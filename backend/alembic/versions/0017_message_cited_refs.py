"""Stage 3: persist RAG citation metadata on `messages`.

Adds a `cited_refs` JSON column to the `messages` table. Each entry
mirrors the SSE `cited_refs` payload — one chunk worth of metadata
(chunk_id / kb_id / kb_doc_id / filename / page / para / bbox /
snippet / score / ragflow_chunk_id / citation_key). Empty list when
the bot had no KB mounted or retrieval returned nothing.

Persisting on the message row lets `/api/messages` re-render
SourceCitation chips on page refresh without re-running retrieval —
the chat history is a complete replay of what the user saw live.

Backward compatible: existing rows get `[]` so the schema drop /
history fetch path stays safe.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017_message_cited_refs"
down_revision: Union[str, None] = "0016_knowledge_base"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "cited_refs",
            sa.JSON,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "cited_refs")