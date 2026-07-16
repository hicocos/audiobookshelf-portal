from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import event
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
