"""RBAC + 群组随机 ID + 审计日志

按 .trae/documents/user-mgmt-audit-log-plan.md 一次性落库：

* users: 加 role / status / display_name / last_login_at / created_by_id
  老用户回填 role='admin'（向后兼容）。
* groups: 加 public_id（12 字符 base62，替换原整数 id 出参）
        + owner_id + scope；老的 group 全部 backfill 一段随机 token，
  owner_id 指向当前 bootstrap admin。
* bots: 加 owner_id + scope；老的 system/protected 自动归 scope='system'。
* 新表 audit_logs：全量写操作流水。

注意：本迁移不在 wire 上立即切换 group id —— 前端同步切换
（router 用 public_id、API body 字段名 group_public_id），但 DB
层面整数 id 仍是主键，所有外键（group_members / runs / messages /
attachments）保持整数不变，仅加 public_id / owner_id / scope 列。
"""
import secrets
import string
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013_rbac_and_audit"
down_revision: Union[str, None] = "0012_task_share_token"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ──────────── helpers ────────────

_TOKEN_ALPHABET = string.ascii_letters + string.digits  # base62
_TOKEN_LENGTH = 12


def _gen_token() -> str:
    return "".join(
        secrets.choice(_TOKEN_ALPHABET) for _ in range(_TOKEN_LENGTH)
    )


# ──────────── upgrade ────────────


def upgrade() -> None:
    # ── 1. groups: 先加 public_id（可空）做 backfill ──
    op.add_column(
        "groups",
        sa.Column("public_id", sa.String(16), nullable=True),
    )
    bind = op.get_bind()

    # 给存量 group 生成随机 public_id（不与 runs.share_token 撞车用同样字典）
    rows = bind.execute(sa.text("SELECT id FROM groups ORDER BY id")).fetchall()
    seen: set[str] = set()
    for (gid,) in rows:
        while True:
            tok = _gen_token()
            # 极小概率撞 runs.share_token：概率约 (n_g * n_r) / 62^12，远低于 1
            dup = bind.execute(
                sa.text("SELECT 1 FROM runs WHERE share_token = :t"), {"t": tok}
            ).first()
            if tok not in seen and not dup:
                seen.add(tok)
                break
        bind.execute(
            sa.text("UPDATE groups SET public_id = :tok WHERE id = :id"),
            {"tok": tok, "id": gid},
        )

    op.alter_column("groups", "public_id", nullable=False)
    op.create_unique_constraint(
        "uq_groups_public_id", "groups", ["public_id"]
    )
    op.create_index("ix_groups_public_id", "groups", ["public_id"])

    # ── 2. groups: 加 owner_id + scope ──
    # 注意：此时 users.role 列尚未添加（见下面的 step 3），不能在这里
    # 查询 role；owner 回填统一放到 step 3 末尾做。
    op.add_column(
        "groups",
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "groups",
        sa.Column(
            "scope",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'user'"),
        ),
    )
    op.create_index("ix_groups_owner", "groups", ["owner_id"])
    op.create_index("ix_groups_scope", "groups", ["scope"])

    # ── 3. users: 加 role / status / display_name / last_login_at / created_by_id ──
    # 注意：必须先把 role 列加上（带默认值 'user'），再 UPDATE 把它改成 'admin'，
    # 再去查 admin id 回填 groups/bots 的 owner_id。先列后查避免
    # "column 'role' does not exist" 错误。
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'user'"),
        ),
    )
    # 老用户默认晋升为 admin（向后兼容）
    bind.execute(sa.text("UPDATE users SET role = 'admin'"))

    op.add_column(
        "users",
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("display_name", sa.String(128), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "created_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_status", "users", ["status"])

    # 现在 role 列就位了，重新取一次 admin id（覆盖之前读到的 None）
    admin_row = bind.execute(
        sa.text(
            "SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1"
        )
    ).first()
    if admin_row:
        # 把 group 的 owner_id 回填指向当前 admin
        bind.execute(
            sa.text("UPDATE groups SET owner_id = :uid WHERE owner_id IS NULL"),
            {"uid": admin_row[0]},
        )

    # ── 4. bots: 加 owner_id + scope ──
    op.add_column(
        "bots",
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "bots",
        sa.Column(
            "scope",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'user'"),
        ),
    )
    # 老 system / protected 自动归 scope='system'
    bind.execute(
        sa.text(
            "UPDATE bots SET scope = 'system' "
            "WHERE is_system = true OR is_protected = true"
        )
    )
    # scope=user 的 bot 归当前 bootstrap admin
    if admin_row:
        bind.execute(
            sa.text(
                "UPDATE bots SET owner_id = :uid WHERE scope = 'user'"
            ),
            {"uid": admin_row[0]},
        )
    op.create_index("ix_bots_owner", "bots", ["owner_id"])
    op.create_index("ix_bots_scope", "bots", ["scope"])
    # 现在 scope 列存在了，回填 bot owner_id 指向 admin
    if admin_row:
        bind.execute(
            sa.text(
                "UPDATE bots SET owner_id = :uid WHERE scope = 'user' AND owner_id IS NULL"
            ),
            {"uid": admin_row[0]},
        )

    # ── 5. 新表 audit_logs ──
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "actor_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_name", sa.String(64), nullable=False, server_default=""),
        sa.Column("actor_role", sa.String(16), nullable=False, server_default="user"),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("target_name", sa.String(256), nullable=True),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'success'"),
        ),
        sa.Column(
            "detail",
            sa.JSON().with_variant(
                sa.dialects.postgresql.JSONB(), "postgresql"
            ),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_audit_occurred_at", "audit_logs", ["occurred_at"], unique=False
    )
    op.create_index(
        "ix_audit_actor", "audit_logs", ["actor_id", "occurred_at"]
    )
    op.create_index(
        "ix_audit_action", "audit_logs", ["action", "occurred_at"]
    )
    op.create_index(
        "ix_audit_target",
        "audit_logs",
        ["target_type", "target_id"],
    )


def downgrade() -> None:
    # 倒序：先 audit_logs，再 bots，再 users，最后 groups
    op.drop_index("ix_audit_target", table_name="audit_logs")
    op.drop_index("ix_audit_action", table_name="audit_logs")
    op.drop_index("ix_audit_actor", table_name="audit_logs")
    op.drop_index("ix_audit_occurred_at", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("ix_bots_scope", table_name="bots")
    op.drop_index("ix_bots_owner", table_name="bots")
    op.drop_column("bots", "scope")
    op.drop_column("bots", "owner_id")

    op.drop_index("ix_users_status", table_name="users")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_column("users", "created_by_id")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "display_name")
    op.drop_column("users", "status")
    op.drop_column("users", "role")

    op.drop_index("ix_groups_scope", table_name="groups")
    op.drop_index("ix_groups_owner", table_name="groups")
    op.drop_column("groups", "scope")
    op.drop_column("groups", "owner_id")
    op.drop_index("ix_groups_public_id", table_name="groups")
    op.drop_constraint("uq_groups_public_id", table_name="groups", type_="unique")
    op.drop_column("groups", "public_id")