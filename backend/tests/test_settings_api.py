import json

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.main import app
from app.models import AppSetting, AuditLog, PortalUser
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
            audit = session.exec(
                select(AuditLog).where(AuditLog.action == "admin.settings.public.update")
            ).one()
            assert json.loads(audit.detail_json or "{}")["fields"] == [
                "client.serverUrl",
                "copy.heroSubtitle",
                "copy.heroTitle",
                "features.registration",
                "features.showLibraryEntry",
                "links.libraryUrl",
                "siteName",
            ]
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


def test_operations_settings_are_exposed_and_can_be_updated():
    client, engine = make_client()
    try:
        with Session(engine) as session:
            session.add(
                AppSetting(
                    key="public_settings",
                    value_json=json.dumps(
                        {
                            "operations": {
                                "inactivityAutoDisable": True,
                                "inactiveDays": 30,
                                "newUserGraceDays": 11,
                                "lastInactivityDisabled": 7,
                            },
                            "features": {"showLibraryEntry": True},
                            "links": {"libraryUrl": "https://listen.example.com"},
                            "telegram": {"inactivityWarningDays": 3},
                        }
                    ),
                )
            )
            session.commit()

        public = client.get("/api/public/config")
        assert public.status_code == 200
        assert public.json()["operations"]["inactivityAutoDisable"] is True
        assert "inactivityWarningDays" not in public.json()["telegram"]

        updated = client.patch(
            "/api/admin/settings/public",
            headers=admin_headers(),
            json={"operations": {"inactiveDays": 45}},
        )
        assert updated.status_code == 200
        settings = updated.json()["settings"]
        assert settings["operations"]["inactiveDays"] == 45
        assert settings["operations"]["inactivityAutoDisable"] is True
        assert settings["operations"]["newUserGraceDays"] == 11
        assert settings["operations"]["lastInactivityDisabled"] == 7
        assert settings["features"]["showLibraryEntry"] is True
        assert settings["links"]["libraryUrl"] == "https://listen.example.com"
    finally:
        app.dependency_overrides.clear()


def test_settings_revision_rejects_stale_admin_save():
    client, _engine = make_client()
    try:
        initial = client.get("/api/admin/settings/public", headers=admin_headers()).json()
        first = client.patch(
            "/api/admin/settings/public",
            headers={**admin_headers(), "If-Match": initial["revision"]},
            json={"siteName": "第一位管理员的修改"},
        )
        assert first.status_code == 200

        stale = client.patch(
            "/api/admin/settings/public",
            headers={**admin_headers(), "If-Match": initial["revision"]},
            json={"tagline": "过期页面提交"},
        )
        assert stale.status_code == 409
        current = client.get("/api/admin/settings/public", headers=admin_headers()).json()
        assert current["settings"]["siteName"] == "第一位管理员的修改"
        assert current["settings"]["tagline"] != "过期页面提交"
    finally:
        app.dependency_overrides.clear()


def test_inactivity_preview_and_library_overview_are_routed():
    client, _engine = make_client()
    try:
        headers = admin_headers()
        assert client.get("/api/library/admin/overview", headers=headers).status_code != 404
        assert (
            client.post(
                "/api/admin/operations/inactivity/preview", headers=headers
            ).status_code
            != 404
        )
        assert client.post("/api/admin/inactivity/check", headers=headers).status_code == 404
        assert client.get("/api/admin/settings/public", headers=headers).status_code == 200
    finally:
        app.dependency_overrides.clear()
