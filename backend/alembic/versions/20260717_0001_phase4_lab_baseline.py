"""Phase 4 PostgreSQL lab baseline.

This revision is for the isolated Phase 4 lab only. It does not migrate the
production SQLite database.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260717_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "portal_users",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("username_normalized", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("telegram_id", sa.String(), nullable=True),
        sa.Column("telegram_username", sa.String(), nullable=True),
        sa.Column("telegram_bound_at", sa.DateTime(), nullable=True),
        sa.Column("session_version", sa.Integer(), nullable=False),
        sa.Column("password_changed_at", sa.DateTime(), nullable=True),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("abs_user_id", sa.String(), nullable=True),
        sa.Column("abs_username", sa.String(), nullable=False),
        sa.Column("abs_username_normalized", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("abs_user_id"),
        sa.UniqueConstraint("abs_username"),
        sa.UniqueConstraint("abs_username_normalized"),
        sa.UniqueConstraint("username"),
        sa.UniqueConstraint("username_normalized"),
    )
    for column in (
        "abs_username",
        "abs_username_normalized",
        "telegram_id",
        "username",
        "username_normalized",
    ):
        op.create_index(f"ix_portal_users_{column}", "portal_users", [column])

    op.create_table(
        "codes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("used_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("designated_username", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_codes_code", "codes", ["code"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("actor_user_id", sa.String(), nullable=True),
        sa.Column("actor_username", sa.String(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=True),
        sa.Column("target_id", sa.String(), nullable=True),
        sa.Column("detail_json", sa.String(), nullable=True),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value_json", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "reconciliation_jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_id", sa.String(), nullable=False),
        sa.Column("abs_user_id", sa.String(), nullable=True),
        sa.Column("payload_json", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(), nullable=False),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("succeeded_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    for column in (
        "abs_user_id",
        "idempotency_key",
        "next_retry_at",
        "operation",
        "status",
        "target_id",
        "target_type",
    ):
        op.create_index(
            f"ix_reconciliation_jobs_{column}", "reconciliation_jobs", [column]
        )

    op.create_table(
        "code_redemptions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("code_id", sa.String(), nullable=False),
        sa.Column("portal_user_id", sa.String(), nullable=True),
        sa.Column("username_snapshot", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["code_id"], ["codes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["portal_user_id"], ["portal_users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_code_redemptions_code_id", "code_redemptions", ["code_id"])
    op.create_index(
        "ix_code_redemptions_portal_user_id", "code_redemptions", ["portal_user_id"]
    )

    op.create_table(
        "telegram_bind_tokens",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("portal_user_id", sa.String(), nullable=False),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["portal_user_id"], ["portal_users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_index("ix_telegram_bind_tokens_code_hash", "telegram_bind_tokens", ["code_hash"])
    op.create_index(
        "ix_telegram_bind_tokens_portal_user_id", "telegram_bind_tokens", ["portal_user_id"]
    )


def downgrade() -> None:
    op.drop_table("telegram_bind_tokens")
    op.drop_table("code_redemptions")
    op.drop_table("reconciliation_jobs")
    op.drop_table("app_settings")
    op.drop_table("audit_logs")
    op.drop_table("codes")
    op.drop_table("portal_users")
