import json
from datetime import UTC, timedelta
from typing import Any, Protocol

from sqlmodel import Session, select

from app.models import PortalUser, ReconciliationJob, utcnow


class AbsReconciliationClient(Protocol):
    async def update_user(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def delete_user(self, user_id: str) -> bool: ...


def _aware(value):
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def enqueue_reconciliation_job(
    session: Session,
    *,
    idempotency_key: str,
    operation: str,
    target_type: str,
    target_id: str,
    abs_user_id: str | None,
    payload: dict[str, Any],
) -> ReconciliationJob:
    existing = session.exec(
        select(ReconciliationJob).where(
            ReconciliationJob.idempotency_key == idempotency_key
        )
    ).first()
    if existing is not None:
        return existing
    job = ReconciliationJob(
        idempotency_key=idempotency_key,
        operation=operation,
        target_type=target_type,
        target_id=target_id,
        abs_user_id=abs_user_id,
        payload_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )
    session.add(job)
    return job


def _current_portal_active_state(session: Session, job: ReconciliationJob) -> bool | None:
    """Resolve the current desired state instead of replaying a stale command.

    Reconciliation jobs are durable and may be retried after a newer admin, expiry,
    renewal, or group-membership action. Portal state is the source of truth for
    portal-user activation, so an old retry must converge ABS to the latest state.
    """

    if job.target_type != "portal_user":
        return None
    user = session.get(PortalUser, job.target_id)
    if user is None:
        return False
    expires_at = _aware(user.expires_at)
    return user.status == "active" and (expires_at is None or expires_at > utcnow())


async def _apply_job(
    session: Session,
    job: ReconciliationJob,
    abs_client: AbsReconciliationClient,
) -> None:
    payload = json.loads(job.payload_json)
    if job.operation == "set_active":
        if not job.abs_user_id:
            raise ValueError("set_active job requires abs_user_id")
        current_state = _current_portal_active_state(session, job)
        desired_state = bool(payload["isActive"]) if current_state is None else current_state
        await abs_client.update_user(job.abs_user_id, {"isActive": desired_state})
        return
    if job.operation == "delete_user":
        if not job.abs_user_id:
            return
        await abs_client.delete_user(job.abs_user_id)
        return
    raise ValueError(f"unsupported reconciliation operation: {job.operation}")


async def process_reconciliation_jobs(
    session: Session,
    abs_client: AbsReconciliationClient,
    *,
    limit: int = 50,
    job_id: str | None = None,
) -> dict[str, int]:
    now = utcnow()
    statement = (
        select(ReconciliationJob)
        .where(
            ReconciliationJob.status.in_(["pending", "retry"]),
            ReconciliationJob.next_retry_at <= now,
        )
        .order_by(ReconciliationJob.created_at)
        .limit(max(1, min(limit, 200)))
    )
    if job_id is not None:
        statement = statement.where(ReconciliationJob.id == job_id)
    jobs = session.exec(statement).all()
    succeeded = 0
    failed = 0
    for job in jobs:
        try:
            await _apply_job(session, job, abs_client)
        except Exception as exc:  # noqa: BLE001 - persist every repair failure
            job.attempts += 1
            job.status = "retry" if job.attempts < 10 else "failed"
            job.last_error = f"{type(exc).__name__}: {exc}"[:2000]
            delay_seconds = min(3600, 5 * (2 ** min(job.attempts - 1, 9)))
            job.next_retry_at = now + timedelta(seconds=delay_seconds)
            job.updated_at = now
            failed += 1
        else:
            job.attempts += 1
            job.status = "succeeded"
            job.last_error = None
            job.succeeded_at = now
            job.updated_at = now
            succeeded += 1
        session.add(job)
        session.commit()
    return {"processed": len(jobs), "succeeded": succeeded, "failed": failed}
