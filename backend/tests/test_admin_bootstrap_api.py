from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.main import app
from app.models import PortalUser


def make_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app), engine


def teardown_client():
    app.dependency_overrides.clear()


def test_bootstrap_admin_creates_first_admin_and_blocks_second(monkeypatch):
    monkeypatch.setenv("ADMIN_SETUP_TOKEN", "test-setup-token")
    client, engine = make_client()
    try:
        response = client.post(
            "/api/admin/bootstrap",
            headers={"X-Admin-Setup-Token": "test-setup-token"},
            json={"username": "admin", "password": "AdminPassword-521"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["user"]["role"] == "admin"
        assert "accessToken" not in data
        assert "moyin_session=" in response.headers["set-cookie"]
        assert "HttpOnly" in response.headers["set-cookie"]
        with Session(engine) as session:
            admin = session.exec(select(PortalUser).where(PortalUser.username == "admin")).first()
            assert admin is not None
            assert admin.role == "admin"
            assert admin.abs_user_id == "portal-admin-local"

        second = client.post(
            "/api/admin/bootstrap",
            headers={"X-Admin-Setup-Token": "test-setup-token"},
            json={"username": "admin2", "password": "AdminPassword-521"},
        )
        assert second.status_code == 409
    finally:
        teardown_client()
