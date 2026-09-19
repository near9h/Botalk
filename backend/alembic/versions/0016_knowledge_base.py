"""knowledge base tables (路线 RAG)

Four new tables:

* `knowledge_bases` — the KB itself. Owned by a user; can be `scope=user`
  (private) or `scope=system` (shared by every bot); `is_public` lets a
  user expose a private KB to other users in read-only mode.

* `kb_documents` — one row per ingested source file (PDF / DOCX / XLSX /
  plain FAQ). `attachment_id` mirrors the existing Attachment row so the
  user-upload pipeline can stay single-sourced. `ragflow_doc_id` /
  `status` track the RAGFlow ingest lifecycle.

* `kb_chunks` — materialized chunk metadata returned from RAGFlow after
  a successful retrieval. `bbox_json` is the four-corner rectangle in
  PDF user-space coordinates that the frontend's pdf.js uses for the
  highlight overlay. `ragflow_chunk_id` is what we send back to RAGFlow
  for cross-references.

* `bot_kb` — many-to-many join between bots and knowledge bases. A bot
  can be mounted on several KBs; a KB can be mounted on several bots.
  The composite PK guarantees idempotent linking.

We intentionally do *not* store chunk vectors or text bodies — RAGFlow
owns those. We only cache the metadata that the chat UI needs to render
the "📎 来源" chip + jump the PDF.js viewer to the right bbox.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016_knowledge_base"
down_revision: Union[str, None] = "0015_attachment_public_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "owner_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        # `scope=user` → only owner + admin can mount. `scope=system`
        # (reserved for the future built-in "项目模板" KB that ships
        # with every install) can be mounted by every bot.
        sa.Column("scope", sa.String(16), nullable=False, server_default="user"),
        # When True, any user can read & mount this KB on their bots
        # (still owner/admin can mutate). Mirrors bots.is_public.
        sa.Column("is_public", sa.Boolean, nullable=False, server_default=sa.text("false")),
        # RAGFlow dataset id — assigned the first time the KB is pushed
        # to the engine. Stays stable for the lifetime of the KB.
        sa.Column("ragflow_dataset_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # Keep public KBs cheap to list and unique-per-name-per-owner.
    op.create_index(
        "uq_kb_owner_name",
        "knowledge_bases",
        ["owner_id", "name"],
        unique=True,
    )

    op.create_table(
        "kb_documents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "kb_id",
            sa.Integer,
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # Mirror of the existing Attachment row, written by the upload
        # pipeline. `group_id IS NULL` on the Attachment to keep KB
        # documents out of the chat-attachment permission surface.
        sa.Column(
            "attachment_id",
            sa.Integer,
            sa.ForeignKey("attachments.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("ragflow_doc_id", sa.String(128), nullable=True),
        # pending | parsing | ready | failed
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text, nullable=False, server_default=""),
        # Chunk count cached from the last successful RAGFlow pull so the
        # KB list page can render "32 chunks" without a remote round-trip.
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "kb_chunks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "kb_doc_id",
            sa.Integer,
            sa.ForeignKey("kb_documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("ragflow_chunk_id", sa.String(128), nullable=True, index=True),
        # 1-indexed page number, NULL for non-paginated sources (Excel / FAQ).
        sa.Column("page", sa.Integer, nullable=True),
        # Optional paragraph / section number within the page. Always
        # NULL for sources without an obvious block structure.
        sa.Column("para", sa.Integer, nullable=True),
        # Four-corner rectangle in PDF user-space coords: [x1, y1, x2, y2].
        # NULL for non-PDF sources. Used by pdf.js for the highlight overlay.
        sa.Column("bbox_json", sa.JSON, nullable=True),
        # Short snippet (first ~200 chars) — useful for the KB list page.
        sa.Column("snippet", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "bot_kb",
        sa.Column(
            "bot_id",
            sa.Integer,
            sa.ForeignKey("bots.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "kb_id",
            sa.Integer,
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        # Multiplier for retrieval score coming back from this KB. Defaults
        # to 1.0; future "domain expert" tuning might lift a project's
        # primary KB above background KBs.
        sa.Column("weight", sa.Float, nullable=False, server_default="1.0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("bot_kb")
    op.drop_table("kb_chunks")
    op.drop_table("kb_documents")
    op.drop_index("uq_kb_owner_name", table_name="knowledge_bases")
    op.drop_table("knowledge_bases")