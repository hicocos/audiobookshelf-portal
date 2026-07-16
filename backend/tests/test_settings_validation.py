from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.main import app
from app.models import PortalUser
from app.security import create_access_token, hash_password


def make_client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(PortalUser(
            id="admin-id",
            username="admin",
            password_hash=hash_password("password"),
            role="admin",
            status="active",
            abs_username="admin",
        ))
        session.commit()

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app, base_url="http://localhost:3009")


def admin_headers():
    token = create_access_token(subject="admin-id", role="admin", session_version=0)
    return {"Authorization": f"Bearer {token}"}


def teardown():
    app.dependency_overrides.clear()


def test_rejects_unknown_deep_settings_fields():
    client = make_client()
    try:
        response = client.patch(
            "/api/admin/settings/public",
            headers=admin_headers(),
            json={"copy": {"heroTitle": "ok", "unexpected": "bad"}},
        )
        assert response.status_code == 422
    finally:
        teardown()


def test_rejects_unsafe_or_insecure_urls():
    client = make_client()
    try:
        for value in ["javascript:alert(1)", "data:text/html,bad", "http://insecure.example"]:
            response = client.patch(
                "/api/admin/settings/public",
                headers=admin_headers(),
                json={"links": {"supportUrl": value}},
            )
            assert response.status_code == 422, value
    finally:
        teardown()


def test_rejects_oversized_arrays_and_text():
    client = make_client()
    try:
        too_many = client.patch(
            "/api/admin/settings/public",
            headers=admin_headers(),
            json={"sections": {"steps": [f"step-{i}" for i in range(31)]}},
        )
        assert too_many.status_code == 422

        too_long = client.patch(
            "/api/admin/settings/public",
            headers=admin_headers(),
            json={"announcement": {"body": "x" * 5001}},
        )
        assert too_long.status_code == 422
    finally:
        teardown()


def test_valid_nested_patch_is_accepted_and_preserves_other_fields():
    client = make_client()
    try:
        first = client.patch(
            "/api/admin/settings/public",
            headers=admin_headers(),
            json={
                "announcement": {
                    "title": "公告",
                    "body": "正文",
                    "timeline": [{"date": "2026-07-16", "body": "维护"}],
                },
                "sections": {"faq": [{"q": "问题", "a": "答案"}]},
            },
        )
        assert first.status_code == 200

        second = client.patch(
            "/api/admin/settings/public",
            headers=admin_headers(),
            json={"copy": {"heroTitle": "新标题"}},
        )
        assert second.status_code == 200
        settings = second.json()["settings"]
        assert settings["announcement"]["timeline"][0]["body"] == "维护"
        assert settings["sections"]["faq"][0]["q"] == "问题"
    finally:
        teardown()
