from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.main import app
from app.models import PortalUser


def make_client(monkeypatch, *, setup_token: str = "setup-token-123"):
    monkeypatch.setenv("ADMIN_SETUP_TOKEN", setup_token)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app, client=("203.0.113.10", 50000)), engine


def teardown():
    app.dependency_overrides.clear()


def test_setup_status_reports_uninitialized_without_exposing_token(monkeypatch):
    client, _engine = make_client(monkeypatch)
    try:
        response = client.get("/api/admin/setup-status")
        assert response.status_code == 200
        assert response.json() == {"initialized": False, "setupAvailable": True}
        assert "setup-token-123" not in response.text
    finally:
        teardown()


def test_bootstrap_requires_setup_token_and_consumes_route_after_initialization(monkeypatch):
    client, engine = make_client(monkeypatch)
    try:
        missing = client.post(
            "/api/admin/bootstrap",
            json={"username": "admin", "password": "AdminPassword-521"},
        )
        assert missing.status_code == 403

        invalid = client.post(
            "/api/admin/bootstrap",
            headers={"X-Admin-Setup-Token": "wrong"},
            json={"username": "admin", "password": "AdminPassword-521"},
        )
        assert invalid.status_code == 403

        created = client.post(
            "/api/admin/bootstrap",
            headers={"X-Admin-Setup-Token": "setup-token-123"},
            json={"username": "admin", "password": "AdminPassword-521"},
        )
        assert created.status_code == 200

        status = client.get("/api/admin/setup-status")
        assert status.json() == {"initialized": True, "setupAvailable": False}

        second = client.post(
            "/api/admin/bootstrap",
            headers={"X-Admin-Setup-Token": "setup-token-123"},
            json={"username": "admin2", "password": "AdminPassword-521"},
        )
        assert second.status_code == 409
        with Session(engine) as session:
            assert len(session.exec(select(PortalUser)).all()) == 1
    finally:
        teardown()
