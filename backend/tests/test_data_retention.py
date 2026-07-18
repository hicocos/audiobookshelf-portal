from datetime import timedelta

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models import (
    PasswordResetToken,
    PortalUser,
    TelegramFlowSession,
    TelegramNotification,
    utcnow,
)
from app.services.data_retention import apply_data_retention


def test_retention_removes_expired_secrets_and_old_terminal_messages_only():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    now = utcnow()
    with Session(engine) as session:
        session.add(
            PortalUser(
                id="user-id",
                username="listener",
                password_hash="hash",
                abs_username="listener",
            )
        )
        session.add_all(
            [
                PasswordResetToken(
                    id="old-token",
                    portal_user_id="user-id",
                    token_hash="old",
                    expires_at=now - timedelta(days=8),
                ),
                PasswordResetToken(
                    id="recent-token",
                    portal_user_id="user-id",
                    token_hash="recent",
                    expires_at=now - timedelta(days=1),
                ),
                TelegramFlowSession(
                    id="old-flow",
                    telegram_id="1",
                    kind="test",
                    step="ready",
                    expires_at=now - timedelta(days=2),
                ),
                TelegramNotification(
                    id="old-sent",
                    dedupe_key="old-sent",
                    telegram_id="1",
                    kind="test",
                    message="done",
                    status="sent",
                    updated_at=now - timedelta(days=181),
                ),
                TelegramNotification(
                    id="old-pending",
                    dedupe_key="old-pending",
                    telegram_id="1",
                    kind="test",
                    message="pending",
                    status="pending",
                    updated_at=now - timedelta(days=181),
                ),
            ]
        )
        session.commit()

        result = apply_data_retention(session)

        assert result["passwordResetTokensDeleted"] == 1
        assert result["telegramFlowsDeleted"] == 1
        assert result["terminalNotificationsDeleted"] == 1
        assert session.get(PasswordResetToken, "recent-token") is not None
        assert session.get(TelegramNotification, "old-pending") is not None
