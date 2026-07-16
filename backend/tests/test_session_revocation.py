from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.main import app
from app.models import PortalUser, utcnow
from app.routers.auth import get_abs_client_factory
from app.security import create_access_token, hash_password


class FakeAbsClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def update_user(self, *_args, **_kwargs):
        return {"ok": True}

    async def list_users(self):
        return []


def make_client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)

    def override_session():
        with Session(engine) as session:
            yield session

    def override_abs_factory():
        return lambda: FakeAbsClient()

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_abs_client_factory] = override_abs_factory
    return TestClient(app, base_url="http://localhost:3009"), engine


def teardown():
    app.dependency_overrides.clear()


def _seed(engine, *, username="alice", role="user", status="active", session_version=0):
    with Session(engine) as session:
        user = PortalUser(
            username=username,
            password_hash=hash_password("old-password"),
            abs_user_id=f"abs-{username}",
            abs_username=username,
            expires_at=utcnow() + timedelta(days=5),
            role=role,
            status=status,
            session_version=session_version,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user.id


def _cookie_for(user_id: str, *, role="user", session_version=0):
    return create_access_token(
        subject=user_id,
        role=role,
        session_version=session_version,
    )


def test_password_change_revokes_previous_cookie():
    client, engine = make_client()
    try:
        user_id = _seed(engine)
        old_cookie = _cookie_for(user_id)
        client.cookies.set("moyin_session", old_cookie)

        changed = client.post(
            "/api/me/password",
            headers={"Origin": "http://localhost:3009"},
            json={"currentPassword": "old-password", "newPassword": "new-password"},
        )
        assert changed.status_code == 200
        assert "moyin_session=" in changed.headers.get("set-cookie", "")

        stale = TestClient(app)
        stale.cookies.set("moyin_session", old_cookie)
        assert stale.get("/api/me").status_code == 401

        current = client.get("/api/me")
        assert current.status_code == 200
    finally:
        teardown()


def test_admin_disable_revokes_existing_cookie():
    client, engine = make_client()
    try:
        admin_id = _seed(engine, username="admin", role="admin")
        user_id = _seed(engine, username="alice")
        admin_cookie = _cookie_for(admin_id, role="admin")
        user_cookie = _cookie_for(user_id)

        client.cookies.set("moyin_session", admin_cookie)
        response = client.post(
            f"/api/admin/users/{user_id}/status",
            headers={"Origin": "http://localhost:3009"},
            json={"action": "disable"},
        )
        assert response.status_code == 200

        stale = TestClient(app)
        stale.cookies.set("moyin_session", user_cookie)
        assert stale.get("/api/me").status_code == 401
    finally:
        teardown()


def test_root_role_uses_privileged_expiry_and_sync_rules():
    client, engine = make_client()
    try:
        root_id = _seed(engine, username="root", role="root", status="active")
        with Session(engine) as session:
            root = session.get(PortalUser, root_id)
            root.expires_at = utcnow() - timedelta(days=1)
            session.add(root)
            session.commit()

        client.cookies.set("moyin_session", _cookie_for(root_id, role="root"))
        response = client.get("/api/me")
        assert response.status_code == 200
        assert response.json()["user"]["role"] == "root"
        assert response.json()["user"]["status"] == "active"
    finally:
        teardown()
