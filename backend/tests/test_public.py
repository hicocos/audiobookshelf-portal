import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.main import app
from app.models import PortalUser
from app.security import create_access_token, hash_password


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
        yield engine
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


def test_session_status_reports_pending_session_as_authenticated(isolated_database):
    with Session(isolated_database) as session:
        user = PortalUser(
            username="pending-user",
            abs_username="pending-user",
            password_hash=hash_password("password"),
            role="user",
            status="pending",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        token = create_access_token(subject=user.id, role=user.role)

    client = TestClient(app)
    client.cookies.set("moyin_session", token)
    response = client.get("/api/public/session-status")

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": True,
        "admin": False,
        "accountStatus": "pending",
        "status": "pending",
        "role": "user",
    }


def test_public_config_exposes_safe_bot_username_for_recovery(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "moyindebot")

    response = TestClient(app).get("/api/public/config")

    assert response.status_code == 200
    assert response.json()["telegram"]["botUsername"] == "moyindebot"


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
