"""Regression tests for login brute-force rate limiting."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.main import app
from app.models import PortalUser, utcnow
from app.rate_limit import login_limiter
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
    return TestClient(app), engine


def teardown():
    app.dependency_overrides.clear()
    login_limiter.reset_all() if hasattr(login_limiter, "reset_all") else login_limiter._hits.clear()


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


def test_login_throttles_repeated_failures():
    client, engine = make_client()
    try:
        _seed(engine)
        # 8 allowed failures, 9th attempt is blocked with 429.
        codes = []
        for _ in range(9):
            r = client.post("/api/auth/login", json={"username": "victim", "password": "wrong"})
            codes.append(r.status_code)
        assert codes[:8] == [401] * 8
        assert codes[8] == 429
    finally:
        teardown()


def test_login_success_resets_counter():
    client, engine = make_client()
    try:
        _seed(engine)
        for _ in range(3):
            client.post("/api/auth/login", json={"username": "victim", "password": "wrong"})
        ok = client.post("/api/auth/login", json={"username": "victim", "password": "CorrectHorse-42"})
        assert ok.status_code == 200
        # After a successful login the failure counter is cleared, so the next
        # wrong attempt starts fresh (not immediately throttled).
        again = client.post("/api/auth/login", json={"username": "victim", "password": "wrong"})
        assert again.status_code == 401
    finally:
        teardown()
