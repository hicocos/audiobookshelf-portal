from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from app.models import OperationPreview, PortalUser, new_id, utcnow


class BulkPreviewError(ValueError):
    pass


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _fingerprint(user: PortalUser) -> dict[str, Any]:
    return {
        "id": user.id,
        "status": user.status,
        "expiresAt": _aware(user.expires_at).isoformat() if user.expires_at else None,
        "updatedAt": _aware(user.updated_at).isoformat(),
    }


def _hash(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_bulk_expiry_preview(
    session: Session,
    *,
    extend_days: int,
    ttl_minutes: int = 15,
) -> dict[str, Any]:
    if extend_days < 1 or extend_days > 3650:
        raise BulkPreviewError("extend days must be between 1 and 3650")
    users = session.exec(
        select(PortalUser)
        .where(
            PortalUser.status != "deleted",
            PortalUser.role.notin_(["admin", "root"]),
        )
        .order_by(PortalUser.created_at, PortalUser.id)
    ).all()
    targets = [_fingerprint(user) for user in users]
    payload = {"extendDays": extend_days, "targets": targets}
    operation_id = new_id()
    preview = OperationPreview(
        kind="bulk_expiry",
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
        "snapshotHash": preview.snapshot_hash,
        "expiresAt": _aware(preview.expires_at).isoformat(),
        "targetIds": [item["id"] for item in targets],
        "targets": targets,
    }


def validate_bulk_expiry_preview(
    session: Session,
    *,
    preview_token: str,
    operation_id: str,
    extend_days: int,
) -> list[PortalUser]:
    preview = session.get(OperationPreview, preview_token)
    if (
        preview is None
        or preview.kind != "bulk_expiry"
        or preview.operation_id != operation_id
    ):
        raise BulkPreviewError("invalid bulk preview")
    if preview.consumed_at is not None:
        raise BulkPreviewError("bulk preview already consumed")
    if _aware(preview.expires_at) <= utcnow():
        raise BulkPreviewError("bulk preview expired")
    try:
        payload = json.loads(preview.payload_json)
    except (json.JSONDecodeError, TypeError) as exc:
        raise BulkPreviewError("invalid bulk preview") from exc
    if int(payload.get("extendDays") or 0) != extend_days:
        raise BulkPreviewError("bulk preview parameters changed")
    if preview.snapshot_hash != _hash(payload):
        raise BulkPreviewError("bulk preview integrity check failed")

    changed: list[str] = []
    users: list[PortalUser] = []
    for stored in payload.get("targets") or []:
        user = session.get(PortalUser, str(stored.get("id") or ""))
        if user is None or _fingerprint(user) != stored:
            changed.append(str(stored.get("id") or "unknown"))
            continue
        users.append(user)
    if changed:
        raise BulkPreviewError(
            "bulk preview targets changed: " + ",".join(changed[:20])
        )
    return users
