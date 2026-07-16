from datetime import timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models import PortalUser, utcnow
from app.services.expiry import sync_expired_users


class FakeAbsClient:
    def __init__(self):
        self.updated = []

    async def update_user(self, user_id, payload):
        self.updated.append((user_id, payload))
        return {"id": user_id, **payload}


@pytest.mark.asyncio
async def test_sync_expired_users_disables_expired_active_users():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    fake_abs = FakeAbsClient()

    with Session(engine) as session:
        expired = PortalUser(
            username="expired",
            password_hash="hash",
            abs_user_id="abs-expired",
            abs_username="expired",
            expires_at=utcnow() - timedelta(minutes=1),
            status="active",
        )
        future = PortalUser(
            username="future",
            password_hash="hash",
            abs_user_id="abs-future",
            abs_username="future",
            expires_at=utcnow() + timedelta(days=1),
            status="active",
        )
        session.add(expired)
        session.add(future)
        session.commit()

        result = await sync_expired_users(session, fake_abs)

        assert result == {"disabled": 1, "failed": 0}
        assert fake_abs.updated == [("abs-expired", {"isActive": False})]
        session.refresh(expired)
        session.refresh(future)
        assert expired.status == "expired"
        assert future.status == "active"


@pytest.mark.asyncio
async def test_sync_never_disables_admin_and_skips_users_without_upstream():
    # Regression: the admin (built-in portal account, abs_user_id may point to a
    # non-existent upstream id) must NEVER be auto-disabled by the expiry sweep,
    # and users with no abs_user_id have nothing to push upstream.
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    fake_abs = FakeAbsClient()

    with Session(engine) as session:
        admin = PortalUser(
            username="admin",
            password_hash="hash",
            role="admin",
            abs_user_id="portal-admin-local",
            abs_username="admin",
            expires_at=utcnow() - timedelta(days=1),
            status="active",
        )
        no_upstream = PortalUser(
            username="no_upstream",
            password_hash="hash",
            abs_user_id=None,
            abs_username="no_upstream",
            expires_at=utcnow() - timedelta(days=1),
            status="active",
        )
        session.add(admin)
        session.add(no_upstream)
        session.commit()

        result = await sync_expired_users(session, fake_abs)

        assert fake_abs.updated == []  # neither account touched upstream
        assert result == {"disabled": 0, "failed": 0}
        session.refresh(admin)
        assert admin.status == "active"  # admin never auto-expired


class FailingAbsClient:
    """Fails for one specific user (simulating a 404 for a deleted upstream
    account) but succeeds for the rest."""

    def __init__(self, fail_id):
        self.updated = []
        self.fail_id = fail_id

    async def update_user(self, user_id, payload):
        if user_id == self.fail_id:
            raise RuntimeError("404 Not Found")
        self.updated.append((user_id, payload))
        return {"id": user_id, **payload}


@pytest.mark.asyncio
async def test_sync_isolates_per_user_upstream_failure():
    # Regression: a single upstream failure (e.g. deleted ABS account -> 404)
    # must NOT crash the whole sweep and leave other expired users un-reconciled.
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    fake_abs = FailingAbsClient(fail_id="abs-broken")

    with Session(engine) as session:
        broken = PortalUser(
            username="broken",
            password_hash="hash",
            abs_user_id="abs-broken",
            abs_username="broken",
            expires_at=utcnow() - timedelta(days=1),
            status="active",
        )
        healthy = PortalUser(
            username="healthy",
            password_hash="hash",
            abs_user_id="abs-healthy",
            abs_username="healthy",
            expires_at=utcnow() - timedelta(days=1),
            status="active",
        )
        session.add(broken)
        session.add(healthy)
        session.commit()

        result = await sync_expired_users(session, fake_abs)

        # The healthy user is still disabled despite the broken one failing.
        assert ("abs-healthy", {"isActive": False}) in fake_abs.updated
        assert result == {"disabled": 1, "failed": 1}
        session.refresh(broken)
        session.refresh(healthy)
        # Both get marked expired locally so the login gate stays correct.
        assert broken.status == "expired"
        assert healthy.status == "expired"


@pytest.mark.asyncio
async def test_sync_reconciles_already_expired_users_with_active_upstream():
    # Regression: once a user is marked 'expired' (by the login gate, set_expiry,
    # or a prior sync), the worker must still ensure the upstream ABS account is
    # disabled. Otherwise an expired user keeps direct app access forever.
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    fake_abs = FakeAbsClient()

    with Session(engine) as session:
        already_expired = PortalUser(
            username="already_expired",
            password_hash="hash",
            abs_user_id="abs-already",
            abs_username="already_expired",
            expires_at=utcnow() - timedelta(days=1),
            status="expired",
        )
        session.add(already_expired)
        session.commit()

        result = await sync_expired_users(session, fake_abs)

        assert ("abs-already", {"isActive": False}) in fake_abs.updated
        assert result["disabled"] >= 1
