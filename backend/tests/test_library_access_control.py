"""Access-control regression tests for the user-facing library endpoint.

`GET /api/library/summary` exposes a user's media library and listening
progress. It must enforce the same login gate as the rest of the portal:
disabled / deleted accounts must be blocked even when their JWT cookie is
still valid, otherwise a revoked user keeps reading their own data.
"""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.main import app
from app.models import PortalUser, utcnow
from app.routers.auth import get_abs_client_factory
from app.security import create_access_token, hash_password


class FakeAbsClient:
    def __init__(self, users=None, user_details=None, current_user=None):
        self.users = users or []
        self.user_details = user_details or {}
        self.current_user = current_user or {}
        self._open = False

    async def __aenter__(self):
        self._open = True
        return self

    async def __aexit__(self, *exc_info):
        self._open = False
        return None

    async def list_libraries(self):
        return [{"id": "lib1", "name": "有声书", "mediaType": "book"}]

    async def list_users(self):
        return self.users

    async def get_current_user(self):
        if not self._open:
            raise RuntimeError("FakeAbsClient must be used as an async context manager")
        return self.current_user

    async def get_user(self, user_id):
        if not self._open:
            raise RuntimeError("FakeAbsClient must be used as an async context manager")
        return self.user_details.get(user_id, {"id": user_id, "mediaProgress": []})

    async def list_library_items(self, library_id, *, limit=8):
        return []

    async def get_library_item(self, item_id):
        return self.user_details.get(f"item:{item_id}", {"id": item_id})


def make_client(fake=None):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_admin(session)
    fake = fake if fake is not None else FakeAbsClient()

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_abs_client_factory] = lambda: (lambda: fake)
    return TestClient(app), engine



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

def teardown_client():
    app.dependency_overrides.clear()


def user_headers(user_id: str):
    return {"Authorization": f"Bearer {create_access_token(subject=user_id, role='user')}"}


def admin_headers():
    return {"Authorization": f"Bearer {create_access_token(subject='admin-id', role='admin')}"}


def _make_user(session: Session, *, status: str, expires_delta: timedelta) -> str:
    user = PortalUser(
        username=f"user_{status}",
        password_hash=hash_password("StrongPassword-521"),
        abs_user_id=f"abs-{status}",
        abs_username=f"user_{status}",
        expires_at=utcnow() + expires_delta,
        status=status,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user.id


def test_library_summary_blocks_disabled_user():
    client, engine = make_client()
    try:
        with Session(engine) as session:
            user_id = _make_user(session, status="disabled", expires_delta=timedelta(days=5))

        response = client.get("/api/library/summary", headers=user_headers(user_id))

        assert response.status_code == 403
        assert response.json()["detail"] == "Account is not active"
    finally:
        teardown_client()


def test_library_summary_blocks_deleted_user():
    client, engine = make_client()
    try:
        with Session(engine) as session:
            user_id = _make_user(session, status="deleted", expires_delta=timedelta(days=5))

        response = client.get("/api/library/summary", headers=user_headers(user_id))

        assert response.status_code == 403
    finally:
        teardown_client()


def test_library_summary_allows_active_user():
    client, engine = make_client()
    try:
        with Session(engine) as session:
            user_id = _make_user(session, status="active", expires_delta=timedelta(days=5))

        response = client.get("/api/library/summary", headers=user_headers(user_id))

        assert response.status_code == 200
        assert "libraries" in response.json()
    finally:
        teardown_client()


def test_library_summary_allows_expired_user_into_portal():
    # Expired users may still see their (now read-only) library in the portal;
    # actual playback is blocked upstream. Portal access itself stays open so
    # they can renew.
    client, engine = make_client()
    try:
        with Session(engine) as session:
            user_id = _make_user(session, status="active", expires_delta=timedelta(minutes=-1))

        response = client.get("/api/library/summary", headers=user_headers(user_id))

        assert response.status_code == 200
    finally:
        teardown_client()


def test_library_summary_uses_authenticated_abs_user_for_portal_admin():
    """Portal-only admin ids must resolve to the ABS token owner via /api/me."""
    current_user = {
        "id": "abs-root",
        "username": "root",
        "permissions": {"accessAllLibraries": True},
        "mediaProgress": [
            {
                "id": "progress-1",
                "libraryItemId": "book-1",
                "progress": 0.25,
                "lastUpdate": 1_700_000_000_000,
            }
        ],
    }
    fake_abs = FakeAbsClient(
        current_user=current_user,
        user_details={
            "item:book-1": {
                "id": "book-1",
                "libraryId": "lib1",
                "media": {
                    "metadata": {
                        "title": "灵境行者",
                        "authorName": "卖报小郎君",
                        "narratorName": "有声的紫襟",
                    }
                },
            }
        },
    )
    client, _engine = make_client(fake_abs)
    try:
        response = client.get("/api/library/summary", headers=admin_headers())

        assert response.status_code == 200
        assert response.json()["stats"] == {
            "libraryCount": 1,
            "itemPreviewCount": 0,
            "progressCount": 1,
        }
        assert response.json()["progress"][0]["title"] == "灵境行者"
        assert response.json()["progress"][0]["author"] == "卖报小郎君"
        assert response.json()["progress"][0]["narrator"] == "有声的紫襟"
    finally:
        teardown_client()


def test_admin_overview_uses_user_detail_progress_for_latest_listen_when_list_users_is_sparse():
    """ABS /api/users can omit mediaProgress; admin activity must fetch details."""
    listened_at = utcnow() - timedelta(days=1)
    listened_ms = int(listened_at.timestamp() * 1000)
    listened_at = datetime.fromtimestamp(listened_ms / 1000, tz=UTC)
    fake_abs = FakeAbsClient(
        users=[{"id": "abs-alice", "username": "alice", "isActive": True, "lastSeen": listened_ms, "mediaProgress": []}],
        user_details={
            "abs-alice": {
                "id": "abs-alice",
                "username": "alice",
                "isActive": True,
                "lastSeen": listened_ms,
                "mediaProgress": [{"id": "p1", "libraryItemId": "book1", "lastUpdate": listened_ms}],
            }
        },
    )
    client, engine = make_client(fake_abs)
    try:
        with Session(engine) as session:
            user = PortalUser(
                username="alice",
                password_hash=hash_password("StrongPassword-521"),
                abs_user_id="abs-alice",
                abs_username="alice",
                expires_at=utcnow() + timedelta(days=5),
                status="active",
                created_at=utcnow() - timedelta(days=10),
            )
            session.add(user)
            session.commit()

        response = client.get("/api/library/admin/overview", headers=admin_headers())

        assert response.status_code == 200
        data = response.json()
        assert data["stats"]["progressCount"] == 1
        assert data["users"][0]["latestListenAt"] == listened_at.isoformat()
        assert data["users"][0]["progressCount"] == 1
        assert data["users"][0]["inactivityReason"] == "最近一个周期内有收听记录"
    finally:
        teardown_client()
