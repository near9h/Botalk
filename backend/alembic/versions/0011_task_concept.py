"""add task concept on runs (title + message_count + index)

This migration renames the conceptual unit of navigation in the chat UI
from "run" to "task" — every task is one user turn plus the multi-bot
reply that follows it. The table is still called `runs` for backwards
compatibility with the orchestrator and message-foreign-key references.

What changes:
  * `runs.title`    — user-facing title (defaulted from user_prompt[:30])
  * `runs.message_count` — materialized count of messages in this task,
                            bumped on every save_message so list views
                            don't need a per-row COUNT(*) join
  * `runs.group_id` index — speeds up the per-group history list
  * Backfill: every existing run gets a default title derived from its
              user_prompt (so old tasks still show a meaningful entry in
              the history drawer).

This pairs with:
  * `app/orchestrator/runner.py` → bumps message_count on each save
  * `app/api/tasks.py`           → /api/groups/{id}/tasks CRUD
  * `app/api/chat.py`            → title is auto-set on the first
                                    message if still empty
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011_task_concept"
down_revision: Union[str, None] = "0010_protected_bots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add the new columns. Both are non-null with sensible defaults so the
    # backfill below is a no-op for new rows; only existing rows need the
    # one-shot UPDATE.
    op.add_column(
        "runs",
        sa.Column("title", sa.String(128), nullable=False, server_default=""),
    )
    op.add_column(
        "runs",
        sa.Column("message_count", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_runs_group_id_started_at",
        "runs",
        ["group_id", sa.text("started_at DESC")],
    )
    # Backfill title for existing rows from user_prompt (first 30 chars,
    # strip whitespace). LEFT(...) is portable across sqlite/postgres
    # (we're running on postgres but keep migration portable for tests).
    op.execute(
        """
        UPDATE runs
           SET title = CASE
             WHEN length(btrim(user_prompt)) = 0 THEN '未命名任务'
             ELSE substr(btrim(user_prompt), 1, 30)
           END
         WHERE title = ''
        """
    )
    # Backfill message_count for tasks that were created before the
    # column existed. New saves (post-migration) bump this column
    # automatically inside save_message().
    op.execute(
        """
        UPDATE runs r
           SET message_count = COALESCE((
             SELECT COUNT(*) FROM messages m WHERE m.run_id = r.id
           ), 0)
         WHERE message_count = 0
        """
    )


def downgrade() -> None:
    op.drop_index("ix_runs_group_id_started_at", table_name="runs")
    op.drop_column("runs", "message_count")
    op.drop_column("runs", "title")
