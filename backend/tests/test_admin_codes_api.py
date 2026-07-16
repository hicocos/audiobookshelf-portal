from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.main import app
from app.models import Code, PortalUser
from app.security import create_access_token, hash_password


def make_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_admin(session)

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app), engine


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
    token = create_access_token(subject="admin-id", role="admin")
    return {"Authorization": f"Bearer {token}"}


def test_admin_can_create_invite_codes():
    client, engine = make_client()
    try:
        response = client.post(
            "/api/admin/codes",
            headers=admin_headers(),
            json={"type": "register", "durationDays": 30, "count": 2, "maxUses": 1, "note": "batch"},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["codes"]) == 2
        assert data["codes"][0]["durationDays"] == 30
        with Session(engine) as session:
            assert len(session.exec(select(Code)).all()) == 2
    finally:
        teardown_client()


def test_admin_can_create_multi_use_code_and_disable_unused_remainder():
    client, engine = make_client()
    try:
        created = client.post(
            "/api/admin/codes",
            headers=admin_headers(),
            json={"type": "renew", "durationDays": 30, "count": 1, "maxUses": 5, "note": "team"},
        )
        assert created.status_code == 200
        code = created.json()["codes"][0]
        assert code["maxUses"] == 5
        assert code["usedCount"] == 0
        assert code["status"] == "active"

        disabled = client.patch(
            f"/api/admin/codes/{code['id']}",
            headers=admin_headers(),
            json={"status": "disabled"},
        )
        assert disabled.status_code == 200
        assert disabled.json()["code"]["status"] == "disabled"

        with Session(engine) as session:
            saved = session.get(Code, code["id"])
            assert saved is not None
            assert saved.max_uses == 5
            assert saved.status == "disabled"
    finally:
        teardown_client()


def test_admin_can_list_codes_and_non_admin_is_forbidden():
    client, engine = make_client()
    try:
        with Session(engine) as session:
            session.add(Code(code="ABCD-EFGH", type="register", duration_days=7))
            session.commit()

        response = client.get("/api/admin/codes", headers=admin_headers())
        assert response.status_code == 200
        assert response.json()["codes"][0]["code"] == "ABCD-EFGH"

        user_token = create_access_token(subject="user-id", role="user")
        forbidden = client.get("/api/admin/codes", headers={"Authorization": f"Bearer {user_token}"})
        assert forbidden.status_code == 403
    finally:
        teardown_client()

def test_admin_can_delete_code_and_its_redemptions():
    client, engine = make_client()
    try:
        with Session(engine) as session:
            code = Code(code="DEL-ETEE-MEEE", type="trial", duration_days=3, used_count=1, max_uses=2)
            session.add(code)
            session.commit()
            session.refresh(code)
            code_id = code.id

        deleted = client.delete(f"/api/admin/codes/{code_id}", headers=admin_headers())
        assert deleted.status_code == 200
        assert deleted.json() == {"ok": True, "id": code_id}

        listed = client.get("/api/admin/codes", headers=admin_headers())
        assert listed.status_code == 200
        assert listed.json()["codes"] == []

        with Session(engine) as session:
            assert session.get(Code, code_id) is None
    finally:
        teardown_client()
