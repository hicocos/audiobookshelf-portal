"""Telegram community administration, requests, and rewards."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260717_0003"
down_revision: str | Sequence[str] | None = "20260717_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telegram_group_memberships",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("portal_user_id", sa.String(), nullable=False),
        sa.Column("telegram_id", sa.String(), nullable=False),
        sa.Column("group_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("left_at", sa.DateTime(), nullable=True),
        sa.Column("grace_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(), nullable=False),
        sa.Column("disabled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["portal_user_id"], ["portal_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("portal_user_id"),
    )
    op.create_index("ix_tg_group_memberships_due", "telegram_group_memberships", ["status", "grace_expires_at"])

    op.create_table(
        "media_requests",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("portal_user_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("details", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("admin_note", sa.String(), nullable=True),
        sa.Column("handled_by_user_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["portal_user_id"], ["portal_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["handled_by_user_id"], ["portal_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_media_requests_user", "media_requests", ["portal_user_id"])
    op.create_index("ix_media_requests_status", "media_requests", ["status"])

    op.create_table(
        "point_accounts",
        sa.Column("portal_user_id", sa.String(), nullable=False),
        sa.Column("balance", sa.Integer(), nullable=False),
        sa.Column("lifetime_earned", sa.Integer(), nullable=False),
        sa.Column("leaderboard_opt_in", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["portal_user_id"], ["portal_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("portal_user_id"),
    )
    op.create_index("ix_point_accounts_leaderboard", "point_accounts", ["leaderboard_opt_in", "lifetime_earned"])

    op.create_table(
        "point_ledger_entries",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("portal_user_id", sa.String(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("reference", sa.String(), nullable=False),
        sa.Column("detail_json", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["portal_user_id"], ["portal_users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference"),
    )
    op.create_index("ix_point_ledger_user_created", "point_ledger_entries", ["portal_user_id", "created_at"])

    op.create_table(
        "daily_checkins",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("portal_user_id", sa.String(), nullable=False),
        sa.Column("local_date", sa.String(), nullable=False),
        sa.Column("streak", sa.Integer(), nullable=False),
        sa.Column("points_awarded", sa.Integer(), nullable=False),
        sa.Column("ledger_entry_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["portal_user_id"], ["portal_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ledger_entry_id"], ["point_ledger_entries.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ledger_entry_id"),
        sa.UniqueConstraint("portal_user_id", "local_date", name="ux_daily_checkins_user_date"),
    )

    op.create_table(
        "referral_invites",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("inviter_user_id", sa.String(), nullable=False),
        sa.Column("code_id", sa.String(), nullable=False),
        sa.Column("used_by_user_id", sa.String(), nullable=True),
        sa.Column("reward_points", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["inviter_user_id"], ["portal_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["code_id"], ["codes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["used_by_user_id"], ["portal_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_id"),
    )
    op.create_index("ix_referral_invites_inviter_created", "referral_invites", ["inviter_user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("referral_invites")
    op.drop_table("daily_checkins")
    op.drop_table("point_ledger_entries")
    op.drop_table("point_accounts")
    op.drop_table("media_requests")
    op.drop_table("telegram_group_memberships")
