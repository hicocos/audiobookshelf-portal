from datetime import UTC, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.main import app
from app.models import Code, PortalUser, ReconciliationJob, TelegramBindToken, utcnow
from app.routers.auth import get_abs_client_factory
from app.security import create_access_token, hash_password


class FakeAbsClient:
    def __init__(self, users=None, fail: Exception | None = None):
        self.users = users or []
        self.fail = fail
        self.updated = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    async def list_users(self):
        if self.fail:
            raise self.fail
        return self.users

    async def update_user(self, user_id, payload):
        if self.fail:
            raise self.fail
        self.updated.append((user_id, payload))
        return {"id": user_id, **payload}


def make_client(fake_abs: FakeAbsClient | None = None):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    fake_abs = fake_abs if fake_abs is not None else FakeAbsClient([
        {"id": "abs-alice", "username": "alice", "isActive": True}
    ])

    def override_session():
        with Session(engine) as session:
            yield session

    def override_abs_factory():
        return lambda: fake_abs

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_abs_client_factory] = override_abs_factory
    return TestClient(app), engine


def teardown_client():
    app.dependency_overrides.clear()


def user_headers(user_id: str):
    token = create_access_token(subject=user_id, role="user")
    return {"Authorization": f"Bearer {token}"}


def create_user(session: Session) -> PortalUser:
    user = PortalUser(
        username="alice",
        password_hash=hash_password("StrongPassword-521"),
        abs_user_id="abs-alice",
        abs_username="alice",
        expires_at=utcnow() + timedelta(days=2),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def test_me_returns_current_user_profile():
    client, engine = make_client()
    try:
        with Session(engine) as session:
            user = create_user(session)

        response = client.get("/api/me", headers=user_headers(user.id))

        assert response.status_code == 200
        data = response.json()["user"]
        assert data["username"] == "alice"
        assert "absUserId" not in data
        assert data["expiresAt"]
    finally:
        teardown_client()


def test_me_marks_portal_user_deleted_when_upstream_user_is_missing():
    client, engine = make_client(FakeAbsClient([]))
    try:
        with Session(engine) as session:
            user = create_user(session)
            user_id = user.id

        response = client.get("/api/me", headers=user_headers(user_id))

        assert response.status_code == 200
        assert response.json()["user"]["status"] == "deleted"
        with Session(engine) as session:
            saved = session.get(PortalUser, user_id)
            assert saved.status == "deleted"
    finally:
        teardown_client()


def test_me_marks_portal_user_disabled_when_upstream_user_is_disabled():
    client, engine = make_client(FakeAbsClient([
        {"id": "abs-alice", "username": "alice", "isActive": False}
    ]))
    try:
        with Session(engine) as session:
            user = create_user(session)
            user_id = user.id

        response = client.get("/api/me", headers=user_headers(user_id))

        assert response.status_code == 200
        assert response.json()["user"]["status"] == "disabled"
        with Session(engine) as session:
            saved = session.get(PortalUser, user_id)
            assert saved.status == "disabled"
    finally:
        teardown_client()


def test_me_keeps_local_status_when_upstream_sync_fails():
    client, engine = make_client(FakeAbsClient(fail=RuntimeError("upstream unavailable")))
    try:
        with Session(engine) as session:
            user = create_user(session)
            user_id = user.id

        response = client.get("/api/me", headers=user_headers(user_id))

        assert response.status_code == 200
        assert response.json()["user"]["status"] == "active"
    finally:
        teardown_client()


def test_redeem_renew_code_extends_expiry_from_existing_future_date():
    client, engine = make_client()
    try:
        with Session(engine) as session:
            user = create_user(session)
            before = user.expires_at
            session.add(Code(code="RENEW-30D", type="renew", duration_days=30))
            session.commit()
            user_id = user.id

        response = client.post(
            "/api/me/redeem",
            headers=user_headers(user_id),
            json={"code": "RENEW-30D"},
        )

        assert response.status_code == 200
        after = response.json()["user"]["expiresAt"]
        assert after > before.isoformat()
        with Session(engine) as session:
            saved = session.get(PortalUser, user_id)
            assert saved.expires_at.date() >= (before + timedelta(days=29)).date()
    finally:
        teardown_client()


def test_me_allows_expired_token_user_and_marks_expired():
    # Expired users need /api/me to load the dashboard where they redeem a code.
    client, engine = make_client(FakeAbsClient([
        {"id": "abs-expired-me", "username": "expired_me", "isActive": False}
    ]))
    try:
        with Session(engine) as session:
            user = PortalUser(
                username="expired_me",
                password_hash=hash_password("StrongPassword-521"),
                abs_user_id="abs-expired-me",
                abs_username="expired_me",
                expires_at=utcnow() - timedelta(minutes=1),
                status="active",
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            user_id = user.id

        response = client.get("/api/me", headers=user_headers(user_id))

        assert response.status_code == 200
        assert response.json()["user"]["status"] == "expired"
        with Session(engine) as session:
            saved = session.get(PortalUser, user_id)
            assert saved.status == "expired"
    finally:
        teardown_client()


def test_redeem_reactivates_expired_user():
    # The core renewal path: an expired user redeems a renew code and is
    # reactivated with a future expiry AND the upstream media account is
    # re-enabled so they can immediately listen again.
    fake_abs = FakeAbsClient([
        {"id": "abs-expired-renew", "username": "expired_renew", "isActive": False}
    ])
    client, engine = make_client(fake_abs)
    try:
        with Session(engine) as session:
            user = PortalUser(
                username="expired_renew",
                password_hash=hash_password("StrongPassword-521"),
                abs_user_id="abs-expired-renew",
                abs_username="expired_renew",
                expires_at=utcnow() - timedelta(days=1),
                status="expired",
            )
            session.add(user)
            session.add(Code(code="RENEW-30D", type="renew", duration_days=30))
            session.commit()
            session.refresh(user)
            user_id = user.id

        response = client.post(
            "/api/me/redeem",
            headers=user_headers(user_id),
            json={"code": "RENEW-30D"},
        )

        assert response.status_code == 200
        assert response.json()["user"]["status"] == "active"
        with Session(engine) as session:
            saved = session.get(PortalUser, user_id)
            assert saved.status == "active"
            saved_expiry = saved.expires_at
            if saved_expiry.tzinfo is None:
                saved_expiry = saved_expiry.replace(tzinfo=UTC)
            assert saved_expiry > utcnow()
        # Upstream media account must be re-enabled on renewal.
        assert ("abs-expired-renew", {"isActive": True}) in fake_abs.updated
    finally:
        teardown_client()


def test_redeem_reports_upstream_reactivation_failure_without_rolling_back_local_renewal():
    fake_abs = FakeAbsClient(fail=RuntimeError("upstream unavailable"))
    client, engine = make_client(fake_abs)
    try:
        with Session(engine) as session:
            user = PortalUser(
                username="expired_local_ok",
                password_hash=hash_password("StrongPassword-521"),
                abs_user_id="abs-expired-local-ok",
                abs_username="expired_local_ok",
                expires_at=utcnow() - timedelta(days=1),
                status="expired",
            )
            session.add(user)
            session.add(Code(code="RENEW-UPSTREAM-DOWN", type="renew", duration_days=30))
            session.commit()
            session.refresh(user)
            user_id = user.id

        response = client.post(
            "/api/me/redeem",
            headers=user_headers(user_id),
            json={"code": "RENEW-UPSTREAM-DOWN"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["user"]["status"] == "active"
        assert body["upstreamReactivated"] is False
        assert "自动重试恢复" in body["message"]
        with Session(engine) as session:
            saved = session.get(PortalUser, user_id)
            assert saved.status == "active"
            assert saved.expires_at.replace(tzinfo=UTC) > utcnow()
            used_code = session.exec(select(Code).where(Code.code == "RENEW-UPSTREAM-DOWN")).first()
            assert used_code.used_count == 1
            job = session.exec(select(ReconciliationJob)).one()
            assert job.status == "pending"
            assert job.operation == "set_active"
            assert job.abs_user_id == "abs-expired-local-ok"
    finally:
        teardown_client()


def test_me_rejects_non_active_token_user():
    client, engine = make_client()
    try:
        with Session(engine) as session:
            user = PortalUser(
                username="disabled_me",
                password_hash=hash_password("StrongPassword-521"),
                abs_user_id="abs-disabled-me",
                abs_username="disabled_me",
                expires_at=utcnow() + timedelta(days=1),
                status="disabled",
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            user_id = user.id

        response = client.get("/api/me", headers=user_headers(user_id))

        assert response.status_code == 403
        assert response.json()["detail"] == "Account is not active"
    finally:
        teardown_client()


def test_me_never_marks_admin_deleted_when_missing_upstream():
    # Admins are portal-native and usually have no matching upstream user.
    # Upstream reconciliation must never corrupt an admin's status.
    client, engine = make_client(FakeAbsClient([]))  # upstream returns no users
    try:
        with Session(engine) as session:
            admin = PortalUser(
                username="root_admin",
                password_hash=hash_password("StrongPassword-521"),
                role="admin",
                abs_user_id="abs-admin",
                abs_username="root_admin",
                expires_at=utcnow() + timedelta(days=1),
                status="active",
            )
            session.add(admin)
            session.commit()
            session.refresh(admin)
            admin_id = admin.id

        token = create_access_token(subject=admin_id, role="admin")
        response = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        with Session(engine) as session:
            saved = session.get(PortalUser, admin_id)
            assert saved.status == "active"
    finally:
        teardown_client()


def test_me_public_user_includes_telegram_binding_status_without_exposing_telegram_id():
    client, engine = make_client()
    try:
        with Session(engine) as session:
            user = create_user(session)
            user.telegram_id = "987654321"
            user.telegram_username = "alice_tg"
            user.telegram_bound_at = utcnow()
            session.add(user)
            session.commit()
            user_id = user.id

        response = client.get("/api/me", headers=user_headers(user_id))

        assert response.status_code == 200
        data = response.json()["user"]
        assert data["telegramBound"] is True
        assert data["telegramUsername"] == "alice_tg"
        assert data["telegramBoundAt"]
        assert "telegramId" not in data
    finally:
        teardown_client()


def test_create_telegram_bind_token_endpoint_returns_code_command_and_does_not_store_plain_code():
    client, engine = make_client()
    try:
        with Session(engine) as session:
            user = create_user(session)
            user_id = user.id

        response = client.post("/api/me/telegram/bind-token", headers=user_headers(user_id))

        assert response.status_code == 200
        body = response.json()
        assert body["code"].startswith("TG-")
        assert body["command"] == f"/bind {body['code']}"
        assert body["expiresAt"]
        assert "botUsername" in body
        with Session(engine) as session:
            tokens = session.exec(select(TelegramBindToken)).all()
            assert len(tokens) == 1
            assert tokens[0].code_hash != body["code"]
            assert body["code"] not in tokens[0].code_hash
    finally:
        teardown_client()


def test_create_telegram_bind_token_endpoint_rejects_already_bound_user():
    client, engine = make_client()
    try:
        with Session(engine) as session:
            user = create_user(session)
            user.telegram_id = "987654321"
            session.add(user)
            session.commit()
            user_id = user.id

        response = client.post("/api/me/telegram/bind-token", headers=user_headers(user_id))

        assert response.status_code == 409
    finally:
        teardown_client()


def test_delete_telegram_binding_endpoint_clears_binding_fields():
    client, engine = make_client()
    try:
        with Session(engine) as session:
            user = create_user(session)
            user.telegram_id = "987654321"
            user.telegram_username = "alice_tg"
            user.telegram_bound_at = utcnow()
            session.add(user)
            session.commit()
            user_id = user.id

        response = client.delete("/api/me/telegram/binding", headers=user_headers(user_id))

        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert response.json()["user"]["telegramBound"] is False
        with Session(engine) as session:
            saved = session.get(PortalUser, user_id)
            assert saved.telegram_id is None
            assert saved.telegram_username is None
            assert saved.telegram_bound_at is None
    finally:
        teardown_client()


def test_delete_telegram_binding_rejects_required_binding_account():
    client, engine = make_client()
    try:
        with Session(engine) as session:
            user = create_user(session)
            user.telegram_id = "987654321"
            user.telegram_bound_at = utcnow()
            user.telegram_binding_required = True
            session.add(user)
            session.commit()
            user_id = user.id

        response = client.delete("/api/me/telegram/binding", headers=user_headers(user_id))

        assert response.status_code == 409
        assert "必须绑定" in response.json()["detail"]
        with Session(engine) as session:
            assert session.get(PortalUser, user_id).telegram_id == "987654321"
    finally:
        teardown_client()

