from datetime import timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import PortalUser, ReconciliationJob, utcnow
from app.services.inactivity import should_disable_for_inactivity, sync_inactive_users


class FakeAbsClient:
    def __init__(self, users):
        self.users = users
        self.updated = []

    async def list_users(self):
        return self.users

    async def update_user(self, user_id, payload):
        self.updated.append((user_id, payload))
        return {"id": user_id, **payload}


def test_new_user_without_progress_is_protected_by_grace_period():
    user = PortalUser(username="newbie", password_hash="hash", abs_username="newbie", abs_user_id="abs-new", created_at=utcnow() - timedelta(days=1), expires_at=utcnow() + timedelta(days=30))
    disable, reason = should_disable_for_inactivity(user, {"id": "abs-new", "isActive": True, "mediaProgress": []}, inactive_days=30, new_user_grace_days=7)
    assert disable is False
    assert "宽限期" in reason


def test_old_user_without_progress_is_inactive_candidate():
    user = PortalUser(username="quiet", password_hash="hash", abs_username="quiet", abs_user_id="abs-quiet", created_at=utcnow() - timedelta(days=10), expires_at=utcnow() + timedelta(days=30))
    disable, reason = should_disable_for_inactivity(user, {"id": "abs-quiet", "isActive": True, "mediaProgress": []}, inactive_days=30, new_user_grace_days=7)
    assert disable is True
    assert "没有任何收听记录" in reason


def test_permanent_user_is_never_an_inactivity_candidate():
    user = PortalUser(
        username="permanent",
        password_hash="hash",
        abs_username="permanent",
        abs_user_id="abs-permanent",
        created_at=utcnow() - timedelta(days=365),
        expires_at=None,
    )
    disable, reason = should_disable_for_inactivity(
        user,
        {"id": "abs-permanent", "isActive": True, "mediaProgress": []},
        inactive_days=30,
        new_user_grace_days=7,
    )
    assert disable is False
    assert "永久账号" in reason


@pytest.mark.asyncio
async def test_sync_inactive_users_disables_only_candidates():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    old = PortalUser(username="old", password_hash="hash", abs_username="old", abs_user_id="abs-old", created_at=utcnow() - timedelta(days=20), expires_at=utcnow() + timedelta(days=30), status="active")
    new = PortalUser(username="new", password_hash="hash", abs_username="new", abs_user_id="abs-new", created_at=utcnow() - timedelta(days=1), expires_at=utcnow() + timedelta(days=30), status="active")
    fake_abs = FakeAbsClient([
        {"id": "abs-old", "isActive": True, "mediaProgress": []},
        {"id": "abs-new", "isActive": True, "mediaProgress": []},
    ])
    with Session(engine) as session:
        session.add(old)
        session.add(new)
        session.commit()
        result = await sync_inactive_users(session, fake_abs, enabled=True, inactive_days=30, new_user_grace_days=7)
        assert result["checked"] == 2
        assert result["disabled"] == 1
        assert [item["username"] for item in result["candidates"]] == ["old"]
        assert result["failed"] == 0
        assert fake_abs.updated == [("abs-old", {"isActive": False})]
        session.refresh(old)
        session.refresh(new)
        assert old.status == "disabled"
        assert new.status == "active"
        job = session.exec(select(ReconciliationJob)).one()
        assert job.status == "succeeded"
