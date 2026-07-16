import re
from secrets import token_hex

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.logging_config import request_id_context
from app.main import app
from app.models import ReconciliationJob


def _client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            ReconciliationJob(
                operation="set_active",
                target_type="portal_user",
                target_id="portal-1",
                abs_user_id="abs-1",
                payload_json='{"isActive":true}',
            )
        )
        session.commit()

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app), engine


def test_request_id_is_preserved_or_generated_and_returned() -> None:
    client, engine = _client()
    try:
        supplied = client.get(
            "/api/public/health/live",
            headers={"X-Request-ID": "edge-123"},
        )
        generated = client.get(
            "/api/public/health/live",
            headers={"X-Request-ID": "contains whitespace"},
        )
    finally:
        app.dependency_overrides.clear()
        client.close()
        engine.dispose()

    assert supplied.headers["X-Request-ID"] == "edge-123"
    assert re.fullmatch(r"[0-9a-f]{32}", generated.headers["X-Request-ID"])


def test_metrics_reject_anonymous_requests() -> None:
    client, engine = _client()
    try:
        response = client.get("/metrics")
    finally:
        app.dependency_overrides.clear()
        client.close()
        engine.dispose()

    assert response.status_code == 404


def test_metrics_cover_http_backlog_and_worker_lag(monkeypatch, tmp_path) -> None:
    worker_state = tmp_path / "worker-health.json"
    worker_state.write_text('{"lastSuccess":1}')
    monkeypatch.setenv("WORKER_HEALTH_STATE_PATH", str(worker_state))
    monkeypatch.setenv("METRICS_TOKEN", "observability-test-token")
    client, engine = _client()
    try:
        client.get("/api/public/health/live")
        response = client.get(
            "/metrics",
            headers={"Authorization": "Bearer observability-test-token"},
        )
    finally:
        app.dependency_overrides.clear()
        client.close()
        engine.dispose()

    assert response.status_code == 200
    assert re.match(r"text/plain; version=(?:0\.0\.4|1\.0\.0)", response.headers["content-type"])
    body = response.text
    assert (
        'moyin_http_requests_total{method="GET",path="/health/live",status="200"}'
        in body
    )
    assert "moyin_http_request_duration_seconds_bucket" in body
    assert 'moyin_reconciliation_backlog{status="pending"} 1.0' in body
    worker_lag = re.search(r"^moyin_worker_lag_seconds ([^\n]+)$", body, re.MULTILINE)
    assert worker_lag is not None
    assert float(worker_lag.group(1)) > 0
    assert 'moyin_dependency_ready{component="audiobookshelf"}' in body


def test_unhandled_exception_returns_request_id_and_resets_context() -> None:
    path = f"/test-observability-error-{token_hex(4)}"

    async def explode():
        raise RuntimeError("expected test failure")

    app.add_api_route(path, explode, methods=["GET"])
    client, engine = _client()
    client.raise_server_exceptions = False
    try:
        failed = client.get(path, headers={"X-Request-ID": "failure-request"})
        healthy = client.get("/api/public/health/live")
    finally:
        app.dependency_overrides.clear()
        client.close()
        engine.dispose()

    assert failed.status_code == 500
    assert failed.headers["X-Request-ID"] == "failure-request"
    assert failed.json() == {"detail": "Internal server error", "requestId": "failure-request"}
    assert healthy.headers["X-Request-ID"] != "failure-request"
    assert request_id_context.get() is None
