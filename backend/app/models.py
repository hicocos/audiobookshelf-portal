from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import UniqueConstraint, event
from sqlmodel import Field, SQLModel


def normalize_username(value: str) -> str:
    """Return the application-wide case-insensitive username identity."""

    return value.casefold()


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


class PortalUser(SQLModel, table=True):
    __tablename__ = "portal_users"

    id: str = Field(default_factory=new_id, primary_key=True)
    username: str = Field(index=True, unique=True)
    username_normalized: str = Field(default="", index=True, unique=True)
    password_hash: str
    email: str | None = None
    telegram_id: str | None = Field(default=None, index=True)
    telegram_username: str | None = None
    telegram_bound_at: datetime | None = None
    session_version: int = 0
    password_changed_at: datetime | None = None
    role: str = "user"
    status: str = "active"
    abs_user_id: str | None = Field(default=None, unique=True)
    abs_username: str = Field(index=True, unique=True)
    abs_username_normalized: str = Field(default="", index=True, unique=True)
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    last_login_at: datetime | None = None

    def __init__(self, **data):
        super().__init__(**data)
        self.sync_normalized_usernames()

    def sync_normalized_usernames(self) -> None:
        self.username_normalized = normalize_username(self.username)
        self.abs_username_normalized = normalize_username(self.abs_username)


@event.listens_for(PortalUser, "before_insert")
@event.listens_for(PortalUser, "before_update")
def _sync_portal_user_normalized_fields(_mapper, _connection, target: PortalUser) -> None:
    target.sync_normalized_usernames()


class Code(SQLModel, table=True):
    __tablename__ = "codes"

    id: str = Field(default_factory=new_id, primary_key=True)
    code: str = Field(index=True, unique=True)
    type: str
    duration_days: int = 30
    max_uses: int = 1
    used_count: int = 0
    status: str = "active"
    designated_username: str | None = None
    expires_at: datetime | None = None
    note: str | None = None
    created_by: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class CodeRedemption(SQLModel, table=True):
    __tablename__ = "code_redemptions"

    id: str = Field(default_factory=new_id, primary_key=True)
    code_id: str = Field(foreign_key="codes.id", ondelete="CASCADE", index=True)
    portal_user_id: str | None = Field(
        default=None,
        foreign_key="portal_users.id",
        ondelete="SET NULL",
        index=True,
    )
    username_snapshot: str
    action: str
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class TelegramBindToken(SQLModel, table=True):
    __tablename__ = "telegram_bind_tokens"

    id: str = Field(default_factory=new_id, primary_key=True)
    portal_user_id: str = Field(foreign_key="portal_users.id", ondelete="CASCADE", index=True)
    code_hash: str = Field(index=True, unique=True)
    expires_at: datetime
    used_at: datetime | None = None
    failed_attempts: int = 0
    created_at: datetime = Field(default_factory=utcnow)


class TelegramFlowSession(SQLModel, table=True):
    __tablename__ = "telegram_flow_sessions"

    id: str = Field(default_factory=new_id, primary_key=True)
    telegram_id: str = Field(index=True, unique=True)
    kind: str = Field(index=True)
    step: str = Field(index=True)
    payload_json: str = "{}"
    expires_at: datetime = Field(index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class PasswordResetToken(SQLModel, table=True):
    __tablename__ = "password_reset_tokens"

    id: str = Field(default_factory=new_id, primary_key=True)
    portal_user_id: str = Field(
        foreign_key="portal_users.id",
        ondelete="CASCADE",
        index=True,
    )
    token_hash: str = Field(index=True, unique=True)
    expires_at: datetime = Field(index=True)
    used_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)


class TelegramNotification(SQLModel, table=True):
    __tablename__ = "telegram_notifications"

    id: str = Field(default_factory=new_id, primary_key=True)
    dedupe_key: str = Field(index=True, unique=True)
    telegram_id: str = Field(index=True)
    kind: str = Field(index=True)
    message: str
    status: str = Field(default="pending", index=True)
    attempts: int = 0
    next_attempt_at: datetime = Field(default_factory=utcnow, index=True)
    claimed_at: datetime | None = None
    sent_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class TelegramGroupMembership(SQLModel, table=True):
    __tablename__ = "telegram_group_memberships"

    id: str = Field(default_factory=new_id, primary_key=True)
    portal_user_id: str = Field(
        foreign_key="portal_users.id",
        ondelete="CASCADE",
        index=True,
        unique=True,
    )
    telegram_id: str = Field(index=True)
    group_id: str = Field(index=True)
    status: str = Field(default="member", index=True)
    left_at: datetime | None = None
    grace_expires_at: datetime | None = Field(default=None, index=True)
    last_checked_at: datetime = Field(default_factory=utcnow)
    disabled_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class MediaRequest(SQLModel, table=True):
    __tablename__ = "media_requests"
    __table_args__ = (
        UniqueConstraint(
            "portal_user_id",
            "open_slot",
            name="ux_media_requests_user_open_slot",
        ),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    portal_user_id: str = Field(
        foreign_key="portal_users.id",
        ondelete="CASCADE",
        index=True,
    )
    kind: str = Field(index=True)
    title: str
    details: str | None = None
    status: str = Field(default="pending", index=True)
    open_slot: int | None = Field(default=None)
    admin_note: str | None = None
    handled_by_user_id: str | None = Field(
        default=None,
        foreign_key="portal_users.id",
        ondelete="SET NULL",
        index=True,
    )
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None


class PointAccount(SQLModel, table=True):
    __tablename__ = "point_accounts"

    portal_user_id: str = Field(
        primary_key=True,
        foreign_key="portal_users.id",
        ondelete="CASCADE",
    )
    balance: int = 0
    lifetime_earned: int = Field(default=0, index=True)
    leaderboard_opt_in: bool = Field(default=False, index=True)
    updated_at: datetime = Field(default_factory=utcnow)


class PointLedgerEntry(SQLModel, table=True):
    __tablename__ = "point_ledger_entries"

    id: str = Field(default_factory=new_id, primary_key=True)
    portal_user_id: str = Field(
        foreign_key="portal_users.id",
        ondelete="CASCADE",
        index=True,
    )
    amount: int
    balance_after: int
    kind: str = Field(index=True)
    reference: str = Field(index=True, unique=True)
    detail_json: str | None = None
    created_at: datetime = Field(default_factory=utcnow, index=True)


class DailyCheckin(SQLModel, table=True):
    __tablename__ = "daily_checkins"
    __table_args__ = (
        UniqueConstraint("portal_user_id", "local_date", name="ux_daily_checkins_user_date"),
    )

    id: str = Field(default_factory=new_id, primary_key=True)
    portal_user_id: str = Field(
        foreign_key="portal_users.id",
        ondelete="CASCADE",
        index=True,
    )
    local_date: str = Field(index=True)
    streak: int
    points_awarded: int
    ledger_entry_id: str = Field(
        foreign_key="point_ledger_entries.id",
        ondelete="RESTRICT",
        unique=True,
    )
    created_at: datetime = Field(default_factory=utcnow)


class ReferralInvite(SQLModel, table=True):
    __tablename__ = "referral_invites"

    id: str = Field(default_factory=new_id, primary_key=True)
    inviter_user_id: str = Field(
        foreign_key="portal_users.id",
        ondelete="CASCADE",
        index=True,
    )
    code_id: str = Field(
        foreign_key="codes.id",
        ondelete="CASCADE",
        index=True,
        unique=True,
    )
    used_by_user_id: str | None = Field(
        default=None,
        foreign_key="portal_users.id",
        ondelete="SET NULL",
        index=True,
    )
    reward_points: int
    expires_at: datetime = Field(index=True)
    settled_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow, index=True)


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"

    id: str = Field(default_factory=new_id, primary_key=True)
    actor_user_id: str | None = None
    actor_username: str | None = None
    action: str
    target_type: str | None = None
    target_id: str | None = None
    detail_json: str | None = None
    ip_address: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class ReconciliationJob(SQLModel, table=True):
    __tablename__ = "reconciliation_jobs"

    id: str = Field(default_factory=new_id, primary_key=True)
    idempotency_key: str = Field(default_factory=new_id, index=True, unique=True)
    operation: str = Field(index=True)
    target_type: str = Field(index=True)
    target_id: str = Field(index=True)
    abs_user_id: str | None = Field(default=None, index=True)
    payload_json: str
    status: str = Field(default="pending", index=True)
    attempts: int = 0
    next_retry_at: datetime = Field(default_factory=utcnow, index=True)
    last_error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    succeeded_at: datetime | None = None


class AppSetting(SQLModel, table=True):
    __tablename__ = "app_settings"

    key: str = Field(primary_key=True)
    value_json: str
    updated_at: datetime = Field(default_factory=utcnow)
