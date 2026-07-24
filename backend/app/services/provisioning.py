from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlmodel import Session, select

from app.models import AccountOperation, ReconciliationJob, utcnow
from app.services.reconciliation import enqueue_reconciliation_job


async def compensate_orphan_abs_user(
    session: Session,
    *,
    abs_factory: Any,
    abs_user_id: str,
    username: str,
    source: str,
) -> dict[str, Any]:
    """Delete a failed provisioning result or durably schedule the same cleanup."""

    key = f"provision-cleanup:{abs_user_id}"
    existing_job = session.exec(
        select(ReconciliationJob).where(ReconciliationJob.idempotency_key == key)
    ).first()
    if existing_job is not None:
        return {
            "compensated": existing_job.status == "succeeded",
            "reconciliationJobId": existing_job.id,
        }
    try:
        async with abs_factory() as abs_client:
            await abs_client.delete_user(abs_user_id)
    except Exception as exc:  # noqa: BLE001 - every cleanup failure becomes durable
        job = enqueue_reconciliation_job(
            session,
            idempotency_key=key,
            operation="delete_user",
            target_type="provisioning_orphan",
            target_id=username,
            abs_user_id=abs_user_id,
            payload={"source": source},
        )
        session.flush()
        operation = session.exec(
            select(AccountOperation).where(
                AccountOperation.idempotency_key == key
            )
        ).first()
        if operation is None:
            operation = AccountOperation(
                kind="account_provisioning",
                idempotency_key=key,
                phase="compensation_pending",
                status="pending",
                request_hash=hashlib.sha256(
                    json.dumps(
                        {"absUserId": abs_user_id, "username": username},
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                last_error=type(exc).__name__,
                reconciliation_job_id=job.id,
            )
        operation.updated_at = utcnow()
        session.add(operation)
        session.commit()
        return {"compensated": False, "reconciliationJobId": job.id}
    return {"compensated": True, "reconciliationJobId": None}
