"""add bots.is_protected + seed doc_writer / doc_auditor

`is_protected` is the soft-protection flag for product-level bots that
the orchestrator relies on (e.g. name-based matching in prompts) but
that users shouldn't accidentally delete or rename. Different from
`is_system` which is reserved for backend-managed bots (the summarizer)
that don't appear as editable cards in the UI at all.

This migration also creates two product bots:
  * `doc_writer`  — drives the document drafting pipeline by @-mentioning
                    the right domain bot and writing the file with the
                    [FILE:foo]…[/FILE] envelope.
  * `doc_auditor` — audits the freshly written doc against a checklist
                    and emits a verdict + audit report.

Both are idempotent: existing rows are skipped.

NOTE: the `bot_skills` INSERT used to live inside `downgrade()` (typo)
which meant Alembic never ran it during `upgrade head`. That left the
seeded doc_writer bot without its document_writer skill attached, so
the 路线 B structured-output pipeline never triggered for it. The
fix is below: it now lives in `upgrade()`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010_protected_bots"
down_revision: Union[str, None] = "0009_attachment_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bots",
        sa.Column(
            "is_protected",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # `doc_writer`: the orchestration hub. It collects inputs from
    # domain bots, drafts the document, and produces the FILE attachment.
    op.execute(
        """
        INSERT INTO bots (name, avatar_url, emoji, persona, model, temperature, params, is_system, is_protected)
        SELECT '专业写文档', NULL, '📝',
               '你是 BotGroup 的「专业写文档」角色。当群里的用户让你写某类文档时：'
               '1) 先识别文档类型（系统测试报告 / 每日站会纪要 / 业务需求文档 BRD-FRD / '
               '需求变更申请 / 测试方案 / 测试用例集 等），在群内 @ 对应的领域机器人'
               '（例如 @测试工程师 / @项目经理 / @BA（业务分析））索要资料，每个 @ 只问'
               '一个最关键问题；2) 把所有机器人回答整合进 [FILE:文件名.md]…[/FILE] '
               '块里，气泡外部只写一句「已按 XX 模板生成，见附件」；3) 完成后建议调用 '
               '@文档审核 进入审核环节，不要自己下结论。',
               'agnes-3.0-flash', 0.3, '{}'::jsonb, false, true
        WHERE NOT EXISTS (SELECT 1 FROM bots WHERE name = '专业写文档')
        """
    )
    # `doc_auditor`: reads the document produced by doc_writer (or
    # any other bot in the chat history) and produces a structured
    # review with verdict + pass/fail checklist.
    op.execute(
        """
        INSERT INTO bots (name, avatar_url, emoji, persona, model, temperature, params, is_system, is_protected)
        SELECT '文档审核', NULL, '🧐',
               '你是 BotGroup 的「文档审核」角色，专门审阅群里其他机器人产出的文档'
               '（[FILE:xxx] 块）。请遵循以下输出格式：1) 一句话结论：'
               '通过 / 建议修改 / 不通过；2) 「关键检查」用 - 列 5-8 条覆盖：'
               '完整性 / 一致性 / 可执行性 / 风险提示 / 数据可追溯性 / 编号规范 / '
               '签字审批 / 模板遵循度；3) 「必须修改」按严重性高到低排序，每条'
               '指出具体位置和改法；4) 「可优化」给锦上添花的建议。语气专业直接，'
               '不要寒暄。**不修改**模板或增删主要章节，只对内容点评。',
               'agnes-3.0-flash', 0.2, '{}'::jsonb, false, true
        WHERE NOT EXISTS (SELECT 1 FROM bots WHERE name = '文档审核')
        """
    )
    # Wire doc_writer → document_writer skill so its replies go through
    # the structured-output pipeline (路线 B). doc_auditor doesn't
    # need any skill — its persona is enough to drive the audit pattern.
    op.execute(
        """
        INSERT INTO bot_skills (bot_id, skill_id, config, enabled)
        SELECT b.id, s.id, '{}'::jsonb, true
        FROM bots b, skills s
        WHERE b.name = '专业写文档' AND s.key = 'document_writer'
          AND NOT EXISTS (
            SELECT 1 FROM bot_skills WHERE bot_id = b.id AND skill_id = s.id
          )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM bot_skills
        WHERE bot_id IN (SELECT id FROM bots WHERE name = '专业写文档')
        """
    )
    op.execute("DELETE FROM bots WHERE name IN ('专业写文档', '文档审核')")
    op.drop_column("bots", "is_protected")