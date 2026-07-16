from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.main import app
from app.models import PortalUser
from app.models import AppSetting
from app.security import create_access_token, hash_password


def make_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_admin(session)

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
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


def admin_headers():
    token = create_access_token(subject="admin-id", role="admin")
    return {"Authorization": f"Bearer {token}"}


def test_public_config_uses_defaults_without_upstream_brand():
    client, _engine = make_client()
    try:
        response = client.get("/api/public/config")
        assert response.status_code == 200
        data = response.json()
        assert data["siteName"] == "MoYin.CC"
        assert data["tagline"] == "安静的声音栖地"
        assert data["passwordMinLength"] == 3
        assert "Audiobookshelf" not in str(data)
        assert data["features"]["registration"] is True
        assert data["copy"]["heroTitle"]
    finally:
        app.dependency_overrides.clear()


def test_admin_can_update_public_settings():
    client, engine = make_client()
    try:
        response = client.patch(
            "/api/admin/settings/public",
            headers=admin_headers(),
            json={
                "siteName": "夜航书馆",
                "copy": {"heroTitle": "今晚听点不一样的", "heroSubtitle": "只展示给用户看的温柔文案"},
                "links": {"libraryUrl": "https://listen.example.com"},
                "client": {"serverUrl": "https://client.example.com"},
                "features": {"registration": False, "showLibraryEntry": True},
            },
        )
        assert response.status_code == 200
        assert response.json()["settings"]["siteName"] == "夜航书馆"

        public = client.get("/api/public/config").json()
        assert public["siteName"] == "夜航书馆"
        assert public["features"]["registration"] is False
        assert public["links"]["libraryUrl"] == "https://listen.example.com"
        assert public["client"]["serverUrl"] == "https://client.example.com"

        with Session(engine) as session:
            assert session.get(AppSetting, "public_settings") is not None
    finally:
        app.dependency_overrides.clear()


def test_non_admin_cannot_update_settings():
    client, _engine = make_client()
    try:
        token = create_access_token(subject="user-id", role="user")
        response = client.patch(
            "/api/admin/settings/public",
            headers={"Authorization": f"Bearer {token}"},
            json={"siteName": "bad"},
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()
