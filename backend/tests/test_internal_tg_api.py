from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.main import app
from app.models import Code, PortalUser, utcnow
from app.routers.auth import get_abs_client_factory
from app.security import hash_password
from app.services.telegram_binding import create_bind_token


class FakeAbsClient:
    def __init__(self):
        self.created = []
        self.libraries = [{"id": "lib1", "name": "内测", "mediaType": "book"}]
        self.user = {
            "id": "abs-alice",
            "username": "alice",
            "isActive": True,
            "permissions": {"accessAllLibraries": True},
            "mediaProgress": [],
        }
        self.items = [
            {
                "id": "book1",
                "libraryId": "lib1",
                "media": {
                    "duration": 3600,
                    "numTracks": 12,
                    "metadata": {
                        "title": "捞尸人",
                        "authorName": "纯洁滴小龙",
                        "narratorName": "方片K",
                    },
                },
                "addedAt": 1710000000000,
            },
            {
                "id": "book2",
                "libraryId": "lib1",
                "media": {
                    "duration": 7200,
                    "numTracks": 20,
                    "metadata": {
                        "title": "三体",
                        "authorName": "刘慈欣",
                        "narratorName": "演播者",
                    },
                },
                "addedAt": 1710000000000,
            },
        ]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    async def list_libraries(self):
        return self.libraries

    async def get_user(self, user_id):
        return dict(self.user, id=user_id)

    async def list_library_items(self, library_id, *, limit=8):
        return self.items[:limit]

    async def search_library(self, library_id, query, *, limit=8):
        needle = query.casefold()
        return [
            item
            for item in self.items
            if needle in str(item.get("media", {}).get("metadata", {}).get("title", "")).casefold()
        ][:limit]

    async def create_user(self, **kwargs):
        self.created.append(kwargs)
        return {"id": "abs-created", "username": kwargs["username"]}


def make_client(monkeypatch, *, internal_token="internal-secret"):
    monkeypatch.setenv("TELEGRAM_BOT_INTERNAL_TOKEN", internal_token)
    monkeypatch.setenv("JWT_SECRET", "test-secret-at-least-32-bytes-long")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    fake_abs = FakeAbsClient()

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_abs_client_factory] = lambda: (lambda: fake_abs)
    return TestClient(app), engine, fake_abs, internal_token


def teardown_client():
    app.dependency_overrides.clear()


def auth_headers(token="internal-secret"):
    return {"Authorization": f"Bearer {token}"}


def seed_user(session: Session, *, telegram_id: str | None = None, status="active", abs_user_id="abs-alice") -> PortalUser:
    user = PortalUser(
        username="alice",
        password_hash=hash_password("StrongPassword-521"),
        abs_user_id=abs_user_id,
        abs_username="alice",
        expires_at=utcnow() + timedelta(days=5),
        status=status,
        telegram_id=telegram_id,
        telegram_username="alice_tg" if telegram_id else None,
        telegram_bound_at=utcnow() if telegram_id else None,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def test_internal_tg_api_requires_configured_bearer_token(monkeypatch):
    client, _engine, _fake_abs, _token = make_client(monkeypatch)
    try:
        missing = client.get("/api/internal/tg/me/123")
        assert missing.status_code == 401

        wrong = client.get("/api/internal/tg/me/123", headers=auth_headers("wrong"))
        assert wrong.status_code == 403
    finally:
        teardown_client()


def test_internal_tg_api_returns_503_when_internal_token_not_configured(monkeypatch):
    client, _engine, _fake_abs, _token = make_client(monkeypatch, internal_token="")
    try:
        response = client.get("/api/internal/tg/me/123", headers=auth_headers("anything"))
        assert response.status_code == 503
    finally:
        teardown_client()


def test_internal_bind_consumes_web_bind_code(monkeypatch):
    client, engine, _fake_abs, token = make_client(monkeypatch)
    try:
        with Session(engine) as session:
            user = seed_user(session)
            code, _bind_token = create_bind_token(session, user)
            user_id = user.id

        response = client.post(
            "/api/internal/tg/bind",
            headers=auth_headers(token),
            json={"code": code, "telegramId": "987654321", "telegramUsername": "alice_tg"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["bound"] is True
        assert body["user"]["username"] == "alice"
        with Session(engine) as session:
            saved = session.get(PortalUser, user_id)
            assert saved.telegram_id == "987654321"
    finally:
        teardown_client()


def test_internal_me_returns_bound_false_for_unknown_telegram_id(monkeypatch):
    client, _engine, _fake_abs, token = make_client(monkeypatch)
    try:
        response = client.get("/api/internal/tg/me/unknown", headers=auth_headers(token))
        assert response.status_code == 200
        assert response.json() == {"bound": False}
    finally:
        teardown_client()


def test_internal_open_is_idempotent_for_existing_abs_account(monkeypatch):
    client, engine, fake_abs, token = make_client(monkeypatch)
    try:
        with Session(engine) as session:
            seed_user(session, telegram_id="987654321")

        response = client.post(
            "/api/internal/tg/open",
            headers=auth_headers(token),
            json={"telegramId": "987654321"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["opened"] is True
        assert body["alreadyOpen"] is True
        assert body["user"]["absUsername"] == "alice"
        assert fake_abs.created == []
    finally:
        teardown_client()


def test_internal_search_returns_bound_user_visible_library_items(monkeypatch):
    client, engine, _fake_abs, token = make_client(monkeypatch)
    try:
        with Session(engine) as session:
            seed_user(session, telegram_id="987654321")

        response = client.get(
            "/api/internal/tg/library/search/987654321?q=捞尸&limit=5",
            headers=auth_headers(token),
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["bound"] is True
        assert body["count"] == 1
        assert body["items"][0]["title"] == "捞尸人"
        assert body["items"][0]["author"] == "纯洁滴小龙"
    finally:
        teardown_client()


def test_internal_register_creates_portal_and_abs_user_bound_to_telegram(monkeypatch):
    client, engine, fake_abs, token = make_client(monkeypatch)
    try:
        with Session(engine) as session:
            session.add(Code(code="INVITE-TG", type="register", duration_days=7))
            session.commit()

        response = client.post(
            "/api/internal/tg/register",
            headers=auth_headers(token),
            json={"telegramId": "987654321", "telegramUsername": "alice_tg", "username": "alice_tg_user", "inviteCode": "INVITE-TG"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["created"] is True
        assert body["bound"] is True
        assert body["oneTimePassword"]
        assert body["user"]["username"] == "alice_tg_user"
        assert fake_abs.created and fake_abs.created[0]["username"] == "alice_tg_user"
        with Session(engine) as session:
            saved = session.get(PortalUser, body["user"]["id"])
            assert saved is not None
            assert saved.telegram_id == "987654321"
            assert saved.telegram_username == "alice_tg"
            code = session.exec(select(Code).where(Code.code == "INVITE-TG")).one()
            assert code.used_count == 1
    finally:
        teardown_client()


def test_internal_register_rejects_when_telegram_already_bound(monkeypatch):
    client, engine, fake_abs, token = make_client(monkeypatch)
    try:
        with Session(engine) as session:
            seed_user(session, telegram_id="987654321")
            session.add(Code(code="INVITE-TG", type="register", duration_days=7))
            session.commit()

        response = client.post(
            "/api/internal/tg/register",
            headers=auth_headers(token),
            json={"telegramId": "987654321", "telegramUsername": "alice_tg", "username": "new_user", "inviteCode": "INVITE-TG"},
        )

        assert response.status_code == 409
        assert fake_abs.created == []
    finally:
        teardown_client()
