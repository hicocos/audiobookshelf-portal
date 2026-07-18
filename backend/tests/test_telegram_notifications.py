from datetime import timedelta

from sqlmodel import Session, SQLModel, create_engine, select

from app.models import PortalUser, TelegramNotification, utcnow
from app.services.telegram_notifications import enqueue_lifecycle_notifications


def test_expiry_reminder_is_queued_once_at_configured_boundary():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            PortalUser(
                username="alice",
                password_hash="hash",
                abs_user_id="abs-alice",
                abs_username="alice",
                telegram_id="42",
                expires_at=utcnow() + timedelta(days=7) - timedelta(minutes=2),
            )
        )
        session.commit()
        settings = {
            "telegram": {
                "lifecycleNotificationsEnabled": True,
                "expiryReminderDays": [7],
            },
        }
        first = enqueue_lifecycle_notifications(
            session,
            public_settings=settings,
        )
        second = enqueue_lifecycle_notifications(
            session,
            public_settings=settings,
        )
        assert first["expiryQueued"] == 1
        assert second["expiryQueued"] == 0
        queued = session.exec(select(TelegramNotification)).all()
        assert len(queued) == 1
        assert queued[0].kind == "expiry_reminder"


def test_lifecycle_notifications_respect_global_feature_switch():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            PortalUser(
                username="alice",
                password_hash="hash",
                abs_username="alice",
                telegram_id="42",
                expires_at=utcnow() + timedelta(days=1),
            )
        )
        session.commit()
        result = enqueue_lifecycle_notifications(
            session,
            public_settings={"telegram": {"lifecycleNotificationsEnabled": False}},
        )
        assert result == {"expiryQueued": 0}
        assert session.exec(select(TelegramNotification)).all() == []
