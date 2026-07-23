from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.main import app
from app.models import Code, PortalUser, utcnow
from app.routers.auth import LoginRequest, RegisterRequest, get_abs_client_factory
from app.routers.me import ChangePasswordRequest
from app.routers.public import PasswordResetRequest
from app.routers.admin_users import CreateUserRequest, SetPasswordRequest
from app.services.codes import redeem_code


def test_all_new_password_inputs_cap_at_18_but_login_keeps_legacy_compatibility():
    assert ChangePasswordRequest(currentPassword="old", newPassword="a" * 18).newPassword == "a" * 18
    assert PasswordResetRequest(token="t" * 32, newPassword="a" * 18).newPassword == "a" * 18
    assert CreateUserRequest(username="alice", password="a" * 18).password == "a" * 18
    assert SetPasswordRequest(password="a" * 18).password == "a" * 18
    for factory in (
        lambda: ChangePasswordRequest(currentPassword="old", newPassword="a" * 19),
        lambda: PasswordResetRequest(token="t" * 32, newPassword="a" * 19),
        lambda: CreateUserRequest(username="alice", password="a" * 19),
        lambda: SetPasswordRequest(password="a" * 19),
    ):
        try:
            factory()
        except ValueError:
            pass
        else:
            raise AssertionError("new passwords longer than 18 characters must be rejected")

    assert LoginRequest(username="alice", password="a" * 19).password == "a" * 19


def test_registration_username_maximum_is_18_without_breaking_existing_logins():
    assert RegisterRequest(
        username="a" * 18,
        password="abc",
        inviteCode="INVITE-CODE",
    ).username == "a" * 18
    try:
        RegisterRequest(
            username="a" * 19,
            password="abc",
            inviteCode="INVITE-CODE",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("registration must reject usernames longer than 18 characters")

    # Existing accounts with legacy longer usernames must remain able to log in.
    assert LoginRequest(username="a" * 19, password="abc").username == "a" * 19


def test_registration_password_maximum_is_18_without_breaking_existing_logins():
    assert RegisterRequest(
        username="alice",
        password="a" * 18,
        inviteCode="INVITE-CODE",
    ).password == "a" * 18
    try:
        RegisterRequest(
            username="alice",
            password="a" * 19,
            inviteCode="INVITE-CODE",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("registration must reject passwords longer than 18 characters")

    # Existing accounts may already use passwords longer than the new registration limit.
    assert LoginRequest(username="alice", password="a" * 19).password == "a" * 19


class FakeAbsClient:
    def __init__(self, *, fail: Exception | None = None):
        self.created = []
        self.updated = []
        self.fail = fail

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    async def create_user(self, **kwargs):
        self.created.append(kwargs)
        if self.fail:
            raise self.fail
        return {"id": "abs-alice", "username": kwargs["username"], "isActive": False}

    async def update_user(self, user_id, payload):
        self.updated.append((user_id, payload))
        return {"id": user_id, **payload}


def make_client(fake_abs: FakeAbsClient | None = None):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    fake_abs = fake_abs or FakeAbsClient()

    def override_session():
        with Session(engine) as session:
            yield session

    def override_abs_factory():
        return lambda: fake_abs

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_abs_client_factory] = override_abs_factory
    return TestClient(app), engine, fake_abs


def teardown_client():
    app.dependency_overrides.clear()


def test_register_with_invite_code_creates_portal_and_abs_user():
    client, engine, fake_abs = make_client()
    try:
        with Session(engine) as session:
            session.add(Code(code="INVITE-123", type="register", duration_days=7))
            session.commit()

        response = client.post(
            "/api/auth/register",
            json={"username": "alice", "password": "StrongPassword-521", "inviteCode": "INVITE-123"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["user"]["username"] == "alice"
        assert "absUserId" not in data["user"]
        assert "accessToken" not in data
        assert "moyin_session=" in response.headers["set-cookie"]
        assert "HttpOnly" in response.headers["set-cookie"]
        assert fake_abs.created[0]["username"] == "alice"
        assert fake_abs.created[0]["permissions"]["accessAllLibraries"] is True
        assert fake_abs.created[0]["permissions"]["accessExplicitContent"] is True
        assert fake_abs.created[0]["is_active"] is False

        with Session(engine) as session:
            saved = session.get(PortalUser, data["user"]["id"])
            assert saved is not None
            assert saved.expires_at is not None
            assert saved.status == "pending"
            assert saved.telegram_binding_required is True
        assert data["user"]["telegramBindingRequired"] is True
        assert data["user"]["telegramBound"] is False
    finally:
        teardown_client()


def test_register_accepts_short_password_matching_media_server_policy(monkeypatch):
    monkeypatch.setenv("PORTAL_PASSWORD_MIN_LENGTH", "3")
    client, engine, fake_abs = make_client()
    try:
        with Session(engine) as session:
            session.add(Code(code="SHORT-PW", type="register", duration_days=7))
            session.commit()

        response = client.post(
            "/api/auth/register",
            json={"username": "bob", "password": "123", "inviteCode": "SHORT-PW"},
        )

        assert response.status_code == 200
        assert response.json()["user"]["username"] == "bob"
        assert fake_abs.created[0]["password"] == "123"
    finally:
        teardown_client()


def test_register_returns_json_error_and_does_not_consume_code_when_upstream_fails():
    client, engine, fake_abs = make_client(FakeAbsClient(fail=RuntimeError("upstream unavailable")))
    try:
        with Session(engine) as session:
            session.add(Code(code="UPSTREAM-FAIL", type="register", duration_days=7))
            session.commit()

        response = client.post(
            "/api/auth/register",
            json={"username": "charlie", "password": "StrongPassword-521", "inviteCode": "UPSTREAM-FAIL"},
        )

        assert response.status_code == 502
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["detail"] == "Upstream media server user creation failed. Please contact the administrator."
        assert fake_abs.created[0]["username"] == "charlie"
        with Session(engine) as session:
            code = session.exec(select(Code).where(Code.code == "UPSTREAM-FAIL")).first()
            assert code is not None
            assert code.used_count == 0
            assert redeem_code(session, "UPSTREAM-FAIL", username="charlie", action="register").used_count == 1
    finally:
        teardown_client()


def test_register_rejects_duplicate_username():
    client, engine, _ = make_client()
    try:
        with Session(engine) as session:
            session.add(Code(code="INVITE-123", type="register", duration_days=7, max_uses=2))
            session.add(
                PortalUser(
                    username="alice",
                    password_hash="hash",
                    abs_user_id="abs-existing",
                    abs_username="alice",
                    expires_at=utcnow() + timedelta(days=1),
                )
            )
            session.commit()

        response = client.post(
            "/api/auth/register",
            json={"username": "alice", "password": "StrongPassword-521", "inviteCode": "INVITE-123"},
        )

        assert response.status_code == 409
    finally:
        teardown_client()


def test_register_blocked_when_registration_disabled():
    """When the admin turns off the registration feature toggle, the backend
    must reject /register even with a valid invite code (UI hiding is not enough)."""
    from app.services.settings import update_public_settings

    client, engine, fake_abs = make_client()
    try:
        with Session(engine) as session:
            session.add(Code(code="INVITE-123", type="register", duration_days=7))
            update_public_settings(session, {"features": {"registration": False}})
            session.commit()

        response = client.post(
            "/api/auth/register",
            json={"username": "alice", "password": "StrongPassword-521", "inviteCode": "INVITE-123"},
        )

        assert response.status_code == 403
        # The invite code must not be consumed and no upstream user created.
        assert fake_abs.created == []
        with Session(engine) as session:
            assert session.exec(select(PortalUser).where(PortalUser.username == "alice")).first() is None
    finally:
        teardown_client()


def test_login_returns_token_for_portal_user():
    client, engine, _ = make_client()
    try:
        from app.security import hash_password

        with Session(engine) as session:
            session.add(
                PortalUser(
                    username="alice",
                    password_hash=hash_password("StrongPassword-521"),
                    abs_user_id="abs-alice",
                    abs_username="alice",
                    expires_at=utcnow() + timedelta(days=1),
                )
            )
            session.commit()

        response = client.post(
            "/api/auth/login",
            json={"username": "alice", "password": "StrongPassword-521"},
        )

        assert response.status_code == 200
        assert "accessToken" not in response.json()
        assert "moyin_session=" in response.headers["set-cookie"]
    finally:
        teardown_client()


def test_login_allows_pending_user_to_enter_portal_and_bind_telegram():
    client, engine, _ = make_client()
    try:
        from app.security import hash_password

        with Session(engine) as session:
            session.add(
                PortalUser(
                    username="pending_user",
                    password_hash=hash_password("StrongPassword-521"),
                    abs_user_id="abs-pending",
                    abs_username="pending_user",
                    expires_at=utcnow() + timedelta(days=1),
                    status="pending",
                    telegram_binding_required=True,
                )
            )
            session.commit()

        response = client.post(
            "/api/auth/login",
            json={"username": "pending_user", "password": "StrongPassword-521"},
        )

        assert response.status_code == 200
        assert response.json()["user"]["status"] == "pending"
        assert response.json()["user"]["telegramBindingRequired"] is True
    finally:
        teardown_client()


def test_pending_required_binding_does_not_expire_before_activation():
    client, engine, _ = make_client()
    try:
        from app.security import hash_password

        with Session(engine) as session:
            session.add(
                PortalUser(
                    username="delayed_binding",
                    password_hash=hash_password("StrongPassword-521"),
                    abs_user_id="abs-delayed",
                    abs_username="delayed_binding",
                    expires_at=utcnow() - timedelta(days=1),
                    status="pending",
                    telegram_binding_required=True,
                )
            )
            session.commit()

        response = client.post(
            "/api/auth/login",
            json={"username": "delayed_binding", "password": "StrongPassword-521"},
        )

        assert response.status_code == 200
        assert response.json()["user"]["status"] == "pending"
    finally:
        teardown_client()


def test_login_allows_expired_user_into_portal_and_marks_expired():
    # Expired users MUST be able to log into the portal so they can redeem a
    # renewal code. Media access is blocked separately by disabling the upstream
    # Audiobookshelf account, not by blocking portal login.
    client, engine, _ = make_client()
    try:
        from app.security import hash_password

        with Session(engine) as session:
            session.add(
                PortalUser(
                    username="expired_user",
                    password_hash=hash_password("StrongPassword-521"),
                    abs_user_id="abs-expired",
                    abs_username="expired_user",
                    expires_at=utcnow() - timedelta(minutes=1),
                    status="active",
                )
            )
            session.commit()

        response = client.post(
            "/api/auth/login",
            json={"username": "expired_user", "password": "StrongPassword-521"},
        )

        assert response.status_code == 200
        assert response.json()["user"]["status"] == "expired"
        assert "moyin_session=" in response.headers.get("set-cookie", "")
        with Session(engine) as session:
            saved = session.exec(select(PortalUser).where(PortalUser.username == "expired_user")).first()
            assert saved.status == "expired"
    finally:
        teardown_client()


def test_login_rejects_disabled_and_deleted_users():
    client, engine, _ = make_client()
    try:
        from app.security import hash_password

        for status in ["disabled", "deleted"]:
            with Session(engine) as session:
                session.add(
                    PortalUser(
                        username=f"{status}_user",
                        password_hash=hash_password("StrongPassword-521"),
                        abs_user_id=f"abs-{status}",
                        abs_username=f"{status}_user",
                        expires_at=utcnow() + timedelta(days=1),
                        status=status,
                    )
                )
                session.commit()

            response = client.post(
                "/api/auth/login",
                json={"username": f"{status}_user", "password": "StrongPassword-521"},
            )

            assert response.status_code == 403
            assert response.json()["detail"] == "Account is not active"
            assert "moyin_session=" not in response.headers.get("set-cookie", "")
    finally:
        teardown_client()


def test_login_allows_admin_even_when_expired():
    client, engine, _ = make_client()
    try:
        from app.security import hash_password

        with Session(engine) as session:
            session.add(
                PortalUser(
                    username="admin",
                    password_hash=hash_password("StrongPassword-521"),
                    role="admin",
                    abs_user_id="abs-admin",
                    abs_username="admin",
                    expires_at=utcnow() - timedelta(days=1),
                    status="active",
                )
            )
            session.commit()

        response = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "StrongPassword-521"},
        )

        assert response.status_code == 200
        assert response.json()["user"]["role"] == "admin"
        assert "moyin_session=" in response.headers.get("set-cookie", "")
    finally:
        teardown_client()
