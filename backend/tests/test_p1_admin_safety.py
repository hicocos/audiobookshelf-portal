from datetime import timedelta

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from sqlmodel import Session, SQLModel, create_engine, select

from app.auth_deps import require_root_for_high_risk
from app.models import AuditLog, PortalUser, TelegramNotification, utcnow
from app.security import create_access_token
from app.services.notification_retry import (
    NotificationRetryError,
    retry_notification_safely,
)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_a18_active_notification_claim_cannot_be_retried_and_stale_retry_is_cas():
    with _session() as session:
        active = TelegramNotification(
            id="notification-active",
            dedupe_key="active-a18",
            telegram_id="18",
            kind="test",
            message="active",
            status="sending",
            claimed_at=utcnow(),
        )
        stale = TelegramNotification(
            id="notification-stale",
            dedupe_key="stale-a18",
            telegram_id="18",
            kind="test",
            message="stale",
            status="sending",
            claimed_at=utcnow() - timedelta(minutes=10),
        )
        session.add(active)
        session.add(stale)
        session.commit()

        with pytest.raises(NotificationRetryError, match="actively sending"):
            retry_notification_safely(
                session,
                active.id,
                actor="admin",
                expected_version=0,
            )
        retried = retry_notification_safely(
            session,
            stale.id,
            actor="admin",
            expected_version=0,
        )
        assert retried.status == "retry"
        assert retried.claimed_at is None
        assert retried.version == 1

        with pytest.raises(NotificationRetryError, match="version"):
            retry_notification_safely(
                session,
                stale.id,
                actor="other-admin",
                expected_version=0,
            )


def test_a16_high_risk_capability_enforces_root_when_present_without_locking_legacy_admin():
    with _session() as session:
        admin = PortalUser(
            id="admin-a16",
            username="admin-a16",
            password_hash="hash",
            abs_username="admin-a16",
            role="admin",
        )
        session.add(admin)
        session.commit()
        request = Request({"type": "http", "headers": []})
        admin_token = create_access_token(subject=admin.id, role="admin")

        fallback_claims = require_root_for_high_risk(
            request=request,
            authorization=f"Bearer {admin_token}",
            session=session,
        )
        assert fallback_claims["capabilityMode"] == "audit_only_no_root"
        assert session.exec(
            select(AuditLog).where(
                AuditLog.action == "capability.high_risk.legacy_admin_fallback"
            )
        ).one()

        root = PortalUser(
            id="root-a16",
            username="root-a16",
            password_hash="hash",
            abs_username="root-a16",
            role="root",
        )
        session.add(root)
        session.commit()

        with pytest.raises(HTTPException) as denied:
            require_root_for_high_risk(
                request=request,
                authorization=f"Bearer {admin_token}",
                session=session,
            )
        assert denied.value.status_code == 403
