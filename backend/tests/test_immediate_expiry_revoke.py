"""Regression: naturally expired members get upstream media access revoked
immediately on portal access (login and /api/me), not only by the worker."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.main import app
from app.models import PortalUser, utcnow
from app.rate_limit import login_limiter
from app.routers.auth import get_abs_client_factory
from app.security import create_access_token, hash_password


_UPDATE_CALLS: list[tuple[str, dict]] = []


class RecordingAbsClient:
    """Records update_user calls (in a module-level list that survives across
    multiple client instantiations within a single request) and serves a stable
    upstream user record."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    async def update_user(self, user_id, payload):
        _UPDATE_CALLS.append((user_id, payload))
        return {"id": user_id, **payload}

    async def list_users(self):
        # Keep the user present upstream so status reconciliation does not flip
        # it to "deleted"; isActive False mirrors the disable we issue.
        return [{"id": "abs-exp", "username": "expiring", "isActive": False}]

    async def get_user(self, user_id):
        return {"id": user_id, "mediaProgress": []}


def make_client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_abs_client_factory] = lambda: (lambda: RecordingAbsClient())
    return TestClient(app), engine


def teardown():
    app.dependency_overrides.clear()
    login_limiter._hits.clear()
    _UPDATE_CALLS.clear()


def _seed_expired(engine):
    with Session(engine) as session:
        user = PortalUser(
            username="expiring",
            password_hash=hash_password("StrongPassword-77"),
            abs_user_id="abs-exp",
            abs_username="expiring",
            expires_at=utcnow() - timedelta(hours=1),  # already expired
            status="active",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user.id


def test_login_revokes_upstream_for_expired_user():
    client, engine = make_client()
    try:
        _seed_expired(engine)
        r = client.post("/api/auth/login", json={"username": "expiring", "password": "StrongPassword-77"})
        # Expired users are still allowed INTO the portal (to renew)...
        assert r.status_code == 200
        assert r.json()["user"]["status"] == "expired"
        # ...but upstream media access must be revoked immediately.
        assert ("abs-exp", {"isActive": False}) in _UPDATE_CALLS
    finally:
        teardown()


def test_me_revokes_upstream_for_expired_user():
    client, engine = make_client()
    try:
        user_id = _seed_expired(engine)
        token = create_access_token(subject=user_id, role="user")
        r = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["user"]["status"] == "expired"
        assert ("abs-exp", {"isActive": False}) in _UPDATE_CALLS
    finally:
        teardown()
