from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.main import app
from app.models import PortalUser
from app.routers.auth import get_abs_client_factory
from app.security import create_access_token, hash_password


class FakeAbsClient:
    def __init__(self, libraries=None, items=None, fail=None):
        self.libraries = libraries or []
        self.items = items or []
        self.fail = fail
        self.requested_limits: list[int] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    async def list_libraries(self):
        if self.fail:
            raise self.fail
        return self.libraries

    async def list_library_items(self, library_id, *, limit=8):
        if self.fail:
            raise self.fail
        self.requested_limits.append(limit)
        return self.items


def make_client(fake):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_admin(session)

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_abs_client_factory] = lambda: (lambda: fake)
    return TestClient(app)


def teardown_client():
    app.dependency_overrides.clear()


def seed_admin(session: Session, *, user_id: str = "admin-id") -> PortalUser:
    admin = PortalUser(
        id=user_id,
        username="admin" if user_id == "admin-id" else user_id,
        password_hash=hash_password("StrongPassword-521"),
        role="admin",
        status="active",
        abs_username="admin" if user_id == "admin-id" else user_id,
    )
    session.add(admin)
    session.commit()
    session.refresh(admin)
    return admin


def admin_headers():
    return {"Authorization": f"Bearer {create_access_token(subject='admin-id', role='admin')}"}


def test_admin_list_libraries():
    fake = FakeAbsClient(libraries=[{"id": "lib1", "name": "有声书", "mediaType": "book"}])
    client = make_client(fake)
    try:
        resp = client.get("/api/library/admin/libraries", headers=admin_headers())
        assert resp.status_code == 200
        libs = resp.json()["libraries"]
        assert libs[0]["id"] == "lib1"
        assert libs[0]["name"] == "有声书"
    finally:
        teardown_client()


def test_admin_list_library_items_clamps_limit():
    fake = FakeAbsClient(items=[{"id": "it1", "media": {"metadata": {"title": "测试作品"}}}])
    client = make_client(fake)
    try:
        resp = client.get(
            "/api/library/admin/libraries/lib1/items?limit=9999", headers=admin_headers()
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["limit"] == 200  # clamped
        assert fake.requested_limits == [200]
        assert data["items"][0]["title"] == "测试作品"
    finally:
        teardown_client()


def test_admin_library_browse_forbidden_for_non_admin():
    client = make_client(FakeAbsClient())
    try:
        token = create_access_token(subject="user-id", role="user")
        resp = client.get("/api/library/admin/libraries", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403
    finally:
        teardown_client()
