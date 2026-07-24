from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from app.models import AccountOperation, OperationPreview, utcnow
from app.services.inactivity import sync_inactive_users
from app.services.settings import get_public_settings, update_public_settings


class InactivityPolicyError(ValueError):
    pass


def _hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def preview_inactivity_policy(
    session: Session,
    abs_client: Any,
    *,
    inactive_days: int,
    new_user_grace_days: int,
    ttl_minutes: int = 15,
) -> dict[str, Any]:
    result = await sync_inactive_users(
        session,
        abs_client,
        enabled=True,
        inactive_days=inactive_days,
        new_user_grace_days=new_user_grace_days,
        actor="inactivity-policy-preview",
        dry_run=True,
    )
    payload = {
        "inactiveDays": inactive_days,
        "newUserGraceDays": new_user_grace_days,
        "targetIds": sorted(item["portalUserId"] for item in result["candidates"]),
    }
    operation_id = hashlib.sha256(
        f"{utcnow().isoformat()}:{_hash(payload)}".encode("utf-8")
    ).hexdigest()
    preview = OperationPreview(
        kind="inactivity_policy",
        operation_id=operation_id,
        payload_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        snapshot_hash=_hash(payload),
        expires_at=utcnow() + timedelta(minutes=max(1, ttl_minutes)),
    )
    session.add(preview)
    session.commit()
    session.refresh(preview)
    return {
        "previewToken": preview.id,
        "operationId": operation_id,
        "candidateCount": len(payload["targetIds"]),
        "candidates": result["candidates"],
        "expiresAt": preview.expires_at.isoformat(),
    }


def confirm_inactivity_policy(
    session: Session,
    *,
    preview_token: str,
    operation_id: str,
    actor: str,
    delay_minutes: int = 60,
) -> AccountOperation:
    preview = session.get(OperationPreview, preview_token)
    if preview is None or preview.kind != "inactivity_policy" or preview.operation_id != operation_id:
        raise InactivityPolicyError("invalid inactivity policy preview")
    if preview.consumed_at is not None or preview.expires_at <= utcnow().replace(tzinfo=None):
        raise InactivityPolicyError("inactivity policy preview expired or consumed")
    payload = json.loads(preview.payload_json)
    if preview.snapshot_hash != _hash(payload):
        raise InactivityPolicyError("inactivity policy preview integrity check failed")
    existing = session.exec(
        select(AccountOperation).where(AccountOperation.idempotency_key == operation_id)
    ).first()
    if existing is not None:
        return existing
    now = utcnow()
    operation = AccountOperation(
        kind="inactivity_policy",
        idempotency_key=operation_id,
        phase="scheduled",
        status="pending",
        request_hash=preview.snapshot_hash,
        result_json=preview.payload_json,
        effective_at=now + timedelta(minutes=max(1, delay_minutes)),
    )
    preview.consumed_at = now
    session.add(preview)
    session.add(operation)
    session.commit()
    session.refresh(operation)
    if operation.effective_at is not None and operation.effective_at.tzinfo is None:
        operation.effective_at = operation.effective_at.replace(tzinfo=now.tzinfo)
    return operation


def cancel_inactivity_policy(session: Session, operation_id: str, *, actor: str) -> AccountOperation:
    operation = session.get(AccountOperation, operation_id)
    if operation is None or operation.kind != "inactivity_policy":
        raise InactivityPolicyError("inactivity policy operation not found")
    if operation.phase == "completed":
        raise InactivityPolicyError("completed inactivity policy cannot be cancelled")
    operation.phase = "cancelled"
    operation.status = "cancelled"
    operation.completed_at = utcnow()
    operation.updated_at = utcnow()
    session.add(operation)
    session.commit()
    session.refresh(operation)
    return operation


async def activate_due_inactivity_policies(
    session: Session,
    abs_client: Any,
    *,
    now: datetime | None = None,
) -> int:
    now = now or utcnow()
    due = session.exec(
        select(AccountOperation).where(
            AccountOperation.kind == "inactivity_policy",
            AccountOperation.phase == "scheduled",
            AccountOperation.effective_at.is_not(None),
            AccountOperation.effective_at <= now,
        )
    ).all()
    activated = 0
    for operation in due:
        payload = json.loads(operation.result_json or "{}")
        result = await sync_inactive_users(
            session,
            abs_client,
            enabled=True,
            inactive_days=int(payload["inactiveDays"]),
            new_user_grace_days=int(payload["newUserGraceDays"]),
            actor="inactivity-policy",
            dry_run=False,
        )
        update_public_settings(
            session,
            {"operations": {"inactivityAutoDisable": True}},
        )
        operation.phase = "completed"
        operation.status = "completed"
        operation.completed_at = utcnow()
        operation.updated_at = utcnow()
        operation.result_json = json.dumps({**payload, "result": result}, ensure_ascii=False)
        session.add(operation)
        session.commit()
        activated += 1
    return activated
