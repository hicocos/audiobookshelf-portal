"""Regression tests for login input bounds and trusted proxy handling."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.main import app
from app.models import PortalUser, utcnow
from app.rate_limit import login_ip_limiter, login_limiter
from app.security import hash_password


def make_client():
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
    login_limiter.reset_all()
    login_ip_limiter.reset_all()


def _seed(engine):
    with Session(engine) as session:
        session.add(PortalUser(
            username="victim",
            password_hash=hash_password("CorrectHorse-42"),
            abs_user_id="abs-victim",
            abs_username="victim",
            expires_at=utcnow() + timedelta(days=5),
            status="active",
        ))
        session.commit()


def test_login_rejects_oversized_fields_before_password_hash(monkeypatch):
    client, engine = make_client()
    try:
        _seed(engine)

        def fail_if_hashed(*_args, **_kwargs):
            raise AssertionError("password verification must not run for oversized input")

        monkeypatch.setattr("app.routers.auth.verify_password", fail_if_hashed)
        response = client.post(
            "/api/auth/login",
            json={"username": "victim", "password": "x" * 257},
        )
        assert response.status_code == 422

        username_response = client.post(
            "/api/auth/login",
            json={"username": "x" * 129, "password": "anything"},
        )
        assert username_response.status_code == 422
    finally:
        teardown()


def test_untrusted_peer_cannot_spoof_x_forwarded_for(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_IPS", "127.0.0.1,::1")
    client, engine = make_client()
    try:
        _seed(engine)
        for index in range(8):
            response = client.post(
                "/api/auth/login",
                headers={"X-Forwarded-For": f"198.51.100.{index}"},
                json={"username": "victim", "password": "wrong"},
            )
            assert response.status_code == 401

        blocked = client.post(
            "/api/auth/login",
            headers={"X-Forwarded-For": "198.51.100.250"},
            json={"username": "victim", "password": "wrong"},
        )
        assert blocked.status_code == 429
    finally:
        teardown()
