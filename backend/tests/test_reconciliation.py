from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.main import app
from app.models import ReconciliationJob, utcnow
from app.routers.auth import get_abs_client_factory
from app.services.reconciliation import process_reconciliation_jobs


class ReactivationClient:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.updated: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    async def update_user(self, user_id: str, payload: dict):
        self.updated.append((user_id, payload))
        if self.fail:
            raise RuntimeError("ABS unavailable")
        return {"id": user_id, **payload}


def test_failed_reactivation_is_persisted_and_visible_to_admin(
    monkeypatch,
):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-for-tests")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    fake = ReactivationClient(fail=True)

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_abs_client_factory] = lambda: (lambda: fake)
    try:
        with Session(engine) as session:
            session.add(
                ReconciliationJob(
                    operation="set_active",
                    target_type="portal_user",
                    target_id="portal-1",
                    abs_user_id="abs-1",
                    payload_json='{"isActive":true}',
                    status="pending",
                    next_retry_at=utcnow() - timedelta(seconds=1),
                )
            )
            session.commit()

        with Session(engine) as session:
            result = __import__("asyncio").run(process_reconciliation_jobs(session, fake))
            assert result == {"processed": 1, "succeeded": 0, "failed": 1}
            job = session.exec(select(ReconciliationJob)).one()
            assert job.status == "retry"
            assert job.attempts == 1
            assert "ABS unavailable" in (job.last_error or "")
            assert job.next_retry_at.replace(tzinfo=job.next_retry_at.tzinfo or utcnow().tzinfo) > utcnow()
    finally:
        app.dependency_overrides.clear()


def test_duplicate_delivery_of_succeeded_job_does_not_repeat_upstream_write():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    fake = ReactivationClient()
    with Session(engine) as session:
        job = ReconciliationJob(
            operation="set_active",
            target_type="portal_user",
            target_id="portal-1",
            abs_user_id="abs-1",
            payload_json='{"isActive":true}',
            status="succeeded",
            idempotency_key="renew:portal-1:code-1",
        )
        session.add(job)
        session.commit()

        result = __import__("asyncio").run(process_reconciliation_jobs(session, fake))

    assert result == {"processed": 0, "succeeded": 0, "failed": 0}
    assert fake.updated == []
