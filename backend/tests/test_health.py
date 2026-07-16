from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.main import app
from app.routers.auth import get_abs_client_factory


class ReadyAbsClient:
    def __init__(self, *, ready: bool = True):
        self.ready = ready

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    async def ping(self):
        if not self.ready:
            raise RuntimeError("unavailable")
        return True


def _client(fake: ReadyAbsClient):
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
    app.dependency_overrides[get_abs_client_factory] = lambda: (lambda: fake)
    return TestClient(app)


def test_liveness_does_not_depend_on_database_or_abs():
    client = _client(ReadyAbsClient(ready=False))
    try:
        response = client.get("/api/public/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "live"}
    finally:
        app.dependency_overrides.clear()


def test_readiness_checks_database_and_abs():
    client = _client(ReadyAbsClient())
    try:
        response = client.get("/api/public/health/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ready", "database": "ok", "audiobookshelf": "ok"}
        metrics = client.get("/metrics").text
        assert 'moyin_dependency_ready{component="database"} 1.0' in metrics
        assert 'moyin_dependency_ready{component="audiobookshelf"} 1.0' in metrics
    finally:
        app.dependency_overrides.clear()


def test_readiness_returns_503_when_abs_is_unavailable():
    client = _client(ReadyAbsClient(ready=False))
    try:
        response = client.get("/api/public/health/ready")
        assert response.status_code == 503
        assert response.json()["detail"]["audiobookshelf"] == "unavailable"
    finally:
        app.dependency_overrides.clear()
