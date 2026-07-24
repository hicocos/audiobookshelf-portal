from __future__ import annotations

import json
from typing import Any

from sqlmodel import Session, select

from app.models import AccountOperation, AuditLog, PortalUser, utcnow
from app.security import hash_password, verify_password


class PasswordSyncError(ValueError):
    pass


def begin_password_sync(
    session: Session,
    user: PortalUser,
    *,
    new_password: str,
    idempotency_key: str,
    actor: str,
) -> AccountOperation:
    key = idempotency_key.strip()
    if not key:
        raise PasswordSyncError("password operation id is required")
    existing = session.exec(
        select(AccountOperation).where(AccountOperation.idempotency_key == key)
    ).first()
    if existing is not None:
        if (
            existing.kind != "password_sync"
            or existing.portal_user_id != user.id
            or not verify_password(new_password, user.password_hash)
        ):
            raise PasswordSyncError("password operation was already used")
        return existing

    now = utcnow()
    operation = AccountOperation(
        kind="password_sync",
        portal_user_id=user.id,
        idempotency_key=key,
        phase="portal_committed",
        status="pending",
    )
    user.password_hash = hash_password(new_password)
    user.password_changed_at = now
    user.session_version = int(user.session_version or 0) + 1
    user.updated_at = now
    session.add(user)
    session.add(operation)
    session.add(
        AuditLog(
            actor_user_id=user.id,
            actor_username=actor,
            action="account.password.portal_updated",
            target_type="portal_user",
            target_id=user.id,
            detail_json=json.dumps({"operationId": operation.id}),
        )
    )
    session.commit()
    session.refresh(user)
    session.refresh(operation)
    return operation


async def retry_password_sync(
    session: Session,
    user: PortalUser,
    *,
    operation: AccountOperation,
    new_password: str,
    abs_factory: Any,
) -> AccountOperation:
    if (
        operation.kind != "password_sync"
        or operation.portal_user_id != user.id
        or not verify_password(new_password, user.password_hash)
    ):
        raise PasswordSyncError("new password does not match the pending operation")
    if operation.phase == "completed":
        return operation

    if user.abs_user_id:
        try:
            async with abs_factory() as abs_client:
                await abs_client.update_user(
                    user.abs_user_id,
                    {"password": new_password},
                )
        except Exception as exc:  # noqa: BLE001 - keep a retryable, secret-free phase
            operation.phase = "upstream_pending"
            operation.status = "pending"
            operation.last_error = type(exc).__name__
            operation.updated_at = utcnow()
            session.add(operation)
            session.commit()
            session.refresh(operation)
            return operation

    now = utcnow()
    operation.phase = "completed"
    operation.status = "completed"
    operation.last_error = None
    operation.result_json = json.dumps(
        {"portalUpdated": True, "upstreamSynced": True},
        separators=(",", ":"),
    )
    operation.completed_at = now
    operation.updated_at = now
    session.add(operation)
    session.add(
        AuditLog(
            actor_user_id=user.id,
            actor_username=user.username,
            action="account.password.upstream_synced",
            target_type="portal_user",
            target_id=user.id,
            detail_json=json.dumps({"operationId": operation.id}),
        )
    )
    session.commit()
    session.refresh(operation)
    return operation


def serialize_password_operation(operation: AccountOperation) -> dict[str, Any]:
    return {
        "operationId": operation.id,
        "phase": operation.phase,
        "portalUpdated": operation.phase
        in {"portal_committed", "upstream_pending", "completed"},
        "upstreamSynced": operation.phase == "completed",
        "retryRequired": operation.phase == "upstream_pending",
        "errorCategory": operation.last_error,
    }
