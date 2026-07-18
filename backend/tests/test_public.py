import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.main import app


@pytest.fixture(autouse=True)
def isolated_database():
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
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_health_endpoint_returns_ok():
    client = TestClient(app)

    response = client.get("/api/public/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_session_status_is_public_and_quiet_for_anonymous_visits():
    client = TestClient(app)

    response = client.get("/api/public/session-status")

    assert response.status_code == 200
    assert response.json() == {"authenticated": False, "admin": False}


def test_public_config_exposes_safe_values_only(monkeypatch):
    monkeypatch.setenv("NEXT_PUBLIC_SITE_NAME", "MoYin.CC")
    monkeypatch.setenv("REGISTRATION_ENABLED", "true")
    monkeypatch.setenv("PORTAL_PASSWORD_MIN_LENGTH", "3")
    monkeypatch.setenv("AUDIOBOOKSHELF_URL", "https://media.example.com/audiobookshelf")
    monkeypatch.setenv("AUDIOBOOKSHELF_ADMIN_TOKEN", "secret-token-must-not-leak")
    client = TestClient(app)

    response = client.get("/api/public/config")

    assert response.status_code == 200
    data = response.json()
    assert data["siteName"] == "MoYin.CC"
    assert data["passwordMinLength"] == 3
    assert data["registrationEnabled"] is True
    assert data["features"]["registration"] is True
    assert "audiobookshelf" not in response.text.lower()
    assert "secret-token-must-not-leak" not in response.text
    assert "admin" not in {key.lower() for key in data.keys()}
