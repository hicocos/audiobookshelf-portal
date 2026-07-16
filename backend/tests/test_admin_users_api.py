from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.main import app
from app.models import AuditLog, PortalUser, utcnow
from app.routers.auth import get_abs_client_factory
from app.security import create_access_token, hash_password, verify_password


class FakeAbsClient:
    """In-memory stand-in for the upstream Audiobookshelf server."""

    def __init__(self, users=None, fail: Exception | None = None):
        self.users = {u["id"]: dict(u) for u in (users or [])}
        self.fail = fail
        self.created: list[dict] = []
        self.updated: list[tuple[str, dict]] = []
        self.deleted: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    async def list_users(self):
        if self.fail:
            raise self.fail
        return list(self.users.values())

    async def create_user(self, *, username, password, permissions=None, type="user", is_active=None):
        if self.fail:
            raise self.fail
        user = {"id": f"abs-{username}", "username": username, "isActive": bool(is_active)}
        self.users[user["id"]] = user
        self.created.append({"username": username, "password": password})
        return user

    async def update_user(self, user_id, payload):
        if self.fail:
            raise self.fail
        self.updated.append((user_id, payload))
        existing = self.users.get(user_id, {"id": user_id})
        if "isActive" in payload:
            existing["isActive"] = payload["isActive"]
        self.users[user_id] = existing
        return existing

    async def delete_user(self, user_id):
        if self.fail:
            raise self.fail
        self.deleted.append(user_id)
        self.users.pop(user_id, None)
        return True


def make_client(fake_abs: FakeAbsClient | None = None):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_admin(session)
    fake_abs = fake_abs if fake_abs is not None else FakeAbsClient()

    def override_session():
        with Session(engine) as session:
            yield session

    def override_abs_factory():
        return lambda: fake_abs

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_abs_client_factory] = override_abs_factory
    return TestClient(app), engine, fake_abs



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


def admin_headers():
    token = create_access_token(subject="admin-id", role="admin")
    return {"Authorization": f"Bearer {token}"}


def seed_user(session: Session, *, username="alice", abs_id="abs-alice", days=10) -> PortalUser:
    user = PortalUser(
        username=username,
        password_hash=hash_password("StrongPassword-521"),
        abs_user_id=abs_id,
        abs_username=username,
        expires_at=utcnow() + timedelta(days=days),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def test_list_users_merges_portal_and_upstream():
    fake = FakeAbsClient([{"id": "abs-alice", "username": "alice", "isActive": True}])
    client, engine, _ = make_client(fake)
    try:
        with Session(engine) as session:
            seed_user(session)
        resp = client.get("/api/admin/users", headers=admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["stats"]["total"] == 1
        assert data["upstreamAvailable"] is True
        assert data["users"][0]["upstreamActive"] is True
    finally:
        teardown_client()


def test_list_users_marks_upstream_unavailable_on_failure():
    client, engine, _ = make_client(FakeAbsClient(fail=RuntimeError("down")))
    try:
        with Session(engine) as session:
            seed_user(session)
        resp = client.get("/api/admin/users", headers=admin_headers())
        assert resp.status_code == 200
        assert resp.json()["upstreamAvailable"] is False
    finally:
        teardown_client()


def test_create_user_creates_portal_and_upstream():
    client, engine, fake = make_client()
    try:
        resp = client.post(
            "/api/admin/users",
            headers=admin_headers(),
            json={"username": "bob", "password": "StrongPassword-521", "durationDays": 30},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()["user"]
        assert body["username"] == "bob"
        assert body["expiresAt"]
        assert fake.created and fake.created[0]["username"] == "bob"
        with Session(engine) as session:
            saved = session.exec(
                __import__("sqlmodel").select(PortalUser).where(PortalUser.username == "bob")
            ).first()
            assert saved is not None and saved.abs_user_id == "abs-bob"
    finally:
        teardown_client()


def test_create_user_rejects_duplicate_username():
    client, engine, _ = make_client()
    try:
        with Session(engine) as session:
            seed_user(session, username="alice")
        resp = client.post(
            "/api/admin/users",
            headers=admin_headers(),
            json={"username": "alice", "password": "StrongPassword-521"},
        )
        assert resp.status_code == 409
    finally:
        teardown_client()


def test_set_password_updates_hash_and_upstream():
    client, engine, fake = make_client(
        FakeAbsClient([{"id": "abs-alice", "username": "alice", "isActive": True}])
    )
    try:
        with Session(engine) as session:
            user = seed_user(session)
            uid = user.id
        resp = client.post(
            f"/api/admin/users/{uid}/password",
            headers=admin_headers(),
            json={"password": "BrandNewPass-999"},
        )
        assert resp.status_code == 200
        assert any("password" in p for _, p in fake.updated)
        with Session(engine) as session:
            saved = session.get(PortalUser, uid)
            assert verify_password("BrandNewPass-999", saved.password_hash)
    finally:
        teardown_client()


def test_disable_and_enable_user_syncs_status():
    fake = FakeAbsClient([{"id": "abs-alice", "username": "alice", "isActive": True}])
    client, engine, _ = make_client(fake)
    try:
        with Session(engine) as session:
            user = seed_user(session)
            uid = user.id
        disabled = client.post(
            f"/api/admin/users/{uid}/status", headers=admin_headers(), json={"action": "disable"}
        )
        assert disabled.status_code == 200
        assert disabled.json()["user"]["status"] == "disabled"
        assert fake.users["abs-alice"]["isActive"] is False

        enabled = client.post(
            f"/api/admin/users/{uid}/status", headers=admin_headers(), json={"action": "enable"}
        )
        assert enabled.json()["user"]["status"] == "active"
        assert fake.users["abs-alice"]["isActive"] is True
    finally:
        teardown_client()


def test_set_expiry_extend_clear_and_absolute():
    client, engine, _ = make_client()
    try:
        with Session(engine) as session:
            user = seed_user(session, days=5)
            uid = user.id
            before = user.expires_at

        extended = client.post(
            f"/api/admin/users/{uid}/expiry", headers=admin_headers(), json={"extendDays": 10}
        )
        assert extended.status_code == 200
        assert extended.json()["user"]["expiresAt"] > before.isoformat()

        cleared = client.post(
            f"/api/admin/users/{uid}/expiry", headers=admin_headers(), json={"clear": True}
        )
        assert cleared.json()["user"]["expiresAt"] is None

        absolute = client.post(
            f"/api/admin/users/{uid}/expiry",
            headers=admin_headers(),
            json={"expiresAt": "2030-01-01T00:00:00+00:00"},
        )
        assert absolute.json()["user"]["expiresAt"].startswith("2030-01-01")
    finally:
        teardown_client()


def test_set_expiry_requires_an_intent():
    client, engine, _ = make_client()
    try:
        with Session(engine) as session:
            user = seed_user(session)
            uid = user.id
        resp = client.post(f"/api/admin/users/{uid}/expiry", headers=admin_headers(), json={})
        assert resp.status_code == 422
    finally:
        teardown_client()


def test_delete_user_marks_deleted_and_calls_upstream():
    fake = FakeAbsClient([{"id": "abs-alice", "username": "alice", "isActive": True}])
    client, engine, _ = make_client(fake)
    try:
        with Session(engine) as session:
            user = seed_user(session)
            uid = user.id
        resp = client.delete(f"/api/admin/users/{uid}", headers=admin_headers())
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert "abs-alice" in fake.deleted
        with Session(engine) as session:
            saved = session.get(PortalUser, uid)
            assert saved.status == "deleted"
    finally:
        teardown_client()


def test_user_mutations_write_audit_logs():
    client, engine, _ = make_client()
    try:
        with Session(engine) as session:
            user = seed_user(session)
            uid = user.id
        client.post(f"/api/admin/users/{uid}/expiry", headers=admin_headers(), json={"clear": True})
        with Session(engine) as session:
            logs = session.exec(select(AuditLog)).all()
            assert any(log.action == "admin.user.set_expiry" for log in logs)
    finally:
        teardown_client()


def test_non_admin_is_forbidden_on_user_endpoints():
    client, engine, _ = make_client()
    try:
        token = create_access_token(subject="user-id", role="user")
        resp = client.get("/api/admin/users", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403
    finally:
        teardown_client()


def test_deleted_users_hidden_from_list():
    fake = FakeAbsClient([{"id": "abs-alice", "username": "alice", "isActive": True}])
    client, engine, _ = make_client(fake)
    try:
        with Session(engine) as session:
            seed_user(session, username="alice", abs_id="abs-alice")
            gone = seed_user(session, username="ghost", abs_id="abs-ghost")
            gone.status = "deleted"
            session.add(gone)
            session.commit()
        data = client.get("/api/admin/users", headers=admin_headers()).json()
        names = [u["username"] for u in data["users"]]
        assert "alice" in names
        assert "ghost" not in names
        assert data["stats"]["total"] == 1
    finally:
        teardown_client()


def test_create_revives_soft_deleted_username():
    client, engine, fake = make_client()
    try:
        with Session(engine) as session:
            user = seed_user(session, username="revive", abs_id="abs-old")
            user.status = "deleted"
            session.add(user)
            session.commit()
            old_id = user.id
        resp = client.post(
            "/api/admin/users",
            headers=admin_headers(),
            json={"username": "revive", "password": "StrongPassword-521", "durationDays": 15},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()["user"]
        # same row reused (id preserved), status active again
        assert body["id"] == old_id
        assert body["status"] == "active"
        # only one row for that username, and it is listed
        data = client.get("/api/admin/users", headers=admin_headers()).json()
        assert [u["username"] for u in data["users"]].count("revive") == 1
    finally:
        teardown_client()


def test_create_still_rejects_active_duplicate():
    client, engine, _ = make_client()
    try:
        with Session(engine) as session:
            seed_user(session, username="dup", abs_id="abs-dup")
        resp = client.post(
            "/api/admin/users",
            headers=admin_headers(),
            json={"username": "dup", "password": "StrongPassword-521", "durationDays": 10},
        )
        assert resp.status_code == 409
    finally:
        teardown_client()


def test_set_expiry_to_past_marks_expired_and_disables_upstream():
    fake = FakeAbsClient([{"id": "abs-alice", "username": "alice", "isActive": True}])
    client, engine, _ = make_client(fake)
    try:
        with Session(engine) as session:
            user = seed_user(session, days=5)
            uid = user.id

        resp = client.post(
            f"/api/admin/users/{uid}/expiry",
            headers=admin_headers(),
            json={"expiresAt": "2000-01-01T00:00:00+00:00"},
        )

        assert resp.status_code == 200
        assert resp.json()["user"]["status"] == "expired"
        assert resp.json()["user"]["upstreamActive"] is False
        assert any(payload.get("isActive") is False for _, payload in fake.updated)
        with Session(engine) as session:
            saved = session.get(PortalUser, uid)
            assert saved.status == "expired"
    finally:
        teardown_client()


def test_set_expiry_from_expired_to_future_reactivates_upstream():
    fake = FakeAbsClient([{"id": "abs-alice", "username": "alice", "isActive": False}])
    client, engine, _ = make_client(fake)
    try:
        with Session(engine) as session:
            user = seed_user(session, days=-1)
            user.status = "expired"
            session.add(user)
            session.commit()
            uid = user.id

        resp = client.post(
            f"/api/admin/users/{uid}/expiry",
            headers=admin_headers(),
            json={"extendDays": 10},
        )

        assert resp.status_code == 200
        assert resp.json()["user"]["status"] == "active"
        assert resp.json()["user"]["upstreamActive"] is True
        assert any(payload.get("isActive") is True for _, payload in fake.updated)
    finally:
        teardown_client()


def test_bulk_extend_expiry_updates_only_finite_non_admin_users():
    fake = FakeAbsClient([
        {"id": "abs-active", "username": "active", "isActive": True},
        {"id": "abs-expired", "username": "expired", "isActive": False},
        {"id": "abs-disabled", "username": "disabled", "isActive": False},
        {"id": "abs-permanent", "username": "permanent", "isActive": True},
        {"id": "abs-admin", "username": "admin", "isActive": True},
    ])
    client, engine, _ = make_client(fake)
    try:
        with Session(engine) as session:
            active = seed_user(session, username="active", abs_id="abs-active", days=10)
            active_id = active.id
            active_before = active.expires_at

            expired = seed_user(session, username="expired", abs_id="abs-expired", days=-2)
            expired_id = expired.id
            expired.status = "expired"

            disabled = seed_user(session, username="disabled", abs_id="abs-disabled", days=4)
            disabled_id = disabled.id
            disabled.status = "disabled"
            disabled_before = disabled.expires_at

            permanent = seed_user(session, username="permanent", abs_id="abs-permanent", days=5)
            permanent_id = permanent.id
            permanent.expires_at = None

            admin = seed_user(session, username="batch_admin", abs_id="abs-admin", days=100)
            admin_id = admin.id
            admin.role = "admin"
            admin_before = admin.expires_at

            session.add(expired)
            session.add(disabled)
            session.add(permanent)
            session.add(admin)
            session.commit()

        resp = client.post(
            "/api/admin/users/bulk/expiry",
            headers=admin_headers(),
            json={"extendDays": 7, "reason": "服务器波动补偿"},
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["summary"] == {
            "matched": 4,
            "updated": 3,
            "reactivated": 1,
            "skippedPermanent": 1,
            "skippedAdmins": 2,
        }
        assert {user["username"] for user in data["users"]} == {"active", "expired", "disabled"}
        assert any(payload.get("isActive") is True for uid, payload in fake.updated if uid == "abs-expired")
        assert not any(uid == "abs-disabled" for uid, _ in fake.updated)
        assert not any(uid == "abs-permanent" for uid, _ in fake.updated)

        with Session(engine) as session:
            saved_active = session.get(PortalUser, active_id)
            saved_expired = session.get(PortalUser, expired_id)
            saved_disabled = session.get(PortalUser, disabled_id)
            saved_permanent = session.get(PortalUser, permanent_id)
            saved_admin = session.get(PortalUser, admin_id)
            assert saved_active.expires_at > active_before + timedelta(days=6)
            assert saved_expired.status == "active"
            assert saved_expired.expires_at.replace(tzinfo=utcnow().tzinfo) > utcnow() + timedelta(days=6)
            assert saved_disabled.status == "disabled"
            assert saved_disabled.expires_at > disabled_before + timedelta(days=6)
            assert saved_permanent.expires_at is None
            assert saved_admin.expires_at == admin_before
            logs = session.exec(select(AuditLog)).all()
            assert any(log.action == "admin.user.bulk_extend_expiry" for log in logs)
    finally:
        teardown_client()


def test_bulk_extend_expiry_preview_does_not_mutate_users():
    client, engine, fake = make_client(FakeAbsClient([
        {"id": "abs-active", "username": "active", "isActive": True},
        {"id": "abs-expired", "username": "expired", "isActive": False},
        {"id": "abs-disabled", "username": "disabled", "isActive": False},
    ]))
    try:
        with Session(engine) as session:
            active = seed_user(session, username="active", abs_id="abs-active", days=10)
            active_id = active.id
            active_before = active.expires_at
            expired = seed_user(session, username="expired", abs_id="abs-expired", days=-2)
            expired.status = "expired"
            disabled = seed_user(session, username="disabled", abs_id="abs-disabled", days=4)
            disabled.status = "disabled"
            permanent = seed_user(session, username="permanent", abs_id="abs-permanent", days=5)
            permanent.expires_at = None
            admin = seed_user(session, username="preview_admin", abs_id="abs-admin", days=100)
            admin.role = "admin"
            session.add(expired)
            session.add(disabled)
            session.add(permanent)
            session.add(admin)
            session.commit()
            expired_id = expired.id
            disabled_id = disabled.id

        resp = client.post(
            "/api/admin/users/bulk/expiry/preview",
            headers=admin_headers(),
            json={"extendDays": 7},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["summary"] == {
            "matched": 4,
            "affected": 3,
            "active": 1,
            "expired": 1,
            "disabled": 1,
            "permanent": 1,
            "reactivatable": 1,
            "skippedAdmins": 2,
        }
        assert fake.updated == []
        with Session(engine) as session:
            assert session.get(PortalUser, active_id).expires_at == active_before
            assert session.get(PortalUser, expired_id).status == "expired"
            assert session.get(PortalUser, disabled_id).status == "disabled"
    finally:
        teardown_client()


def admin_headers_for(user_id: str):
    token = create_access_token(subject=user_id, role="admin")
    return {"Authorization": f"Bearer {token}"}


def test_admin_token_is_rechecked_against_database_status_and_role():
    client, engine, _ = make_client()
    try:
        demoted_id = "demoted-admin"
        disabled_id = "disabled-admin"
        with Session(engine) as session:
            session.add(PortalUser(
                id=demoted_id,
                username="demoted",
                password_hash=hash_password("StrongPassword-521"),
                role="user",
                status="active",
                abs_username="demoted",
            ))
            session.add(PortalUser(
                id=disabled_id,
                username="disabled-admin",
                password_hash=hash_password("StrongPassword-521"),
                role="admin",
                status="disabled",
                abs_username="disabled-admin",
            ))
            session.commit()

        assert client.get("/api/admin/users", headers=admin_headers_for(demoted_id)).status_code == 403
        assert client.get("/api/admin/users", headers=admin_headers_for(disabled_id)).status_code == 403
    finally:
        teardown_client()


def test_admin_cannot_disable_or_delete_self_or_last_admin():
    client, engine, _ = make_client()
    try:
        self_disable = client.post(
            "/api/admin/users/admin-id/status",
            headers=admin_headers(),
            json={"action": "disable"},
        )
        assert self_disable.status_code == 400

        self_delete = client.delete("/api/admin/users/admin-id", headers=admin_headers())
        assert self_delete.status_code == 400

        with Session(engine) as session:
            second = seed_admin(session, user_id="admin-2")
            second.username = "admin2"
            second.abs_username = "admin2"
            session.add(second)
            session.commit()

        delete_second = client.delete("/api/admin/users/admin-2", headers=admin_headers())
        assert delete_second.status_code == 200

        with Session(engine) as session:
            saved_self = session.get(PortalUser, "admin-id")
            saved_second = session.get(PortalUser, "admin-2")
            assert saved_self.status == "active"
            assert saved_second.status == "deleted"
    finally:
        teardown_client()
