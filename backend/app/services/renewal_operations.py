from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import Session

from app.models import Code, OperationPreview, PortalUser, new_id, utcnow
from app.services.account_lifecycle import preview_renewal
from app.services.codes import CodeValidationError, validate_code


class RenewalPreviewError(ValueError):
    pass


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _user_snapshot(user: PortalUser) -> dict[str, Any]:
    return {
        "status": user.status,
        "expiresAt": _aware(user.expires_at).isoformat() if user.expires_at else None,
        "sessionVersion": int(user.session_version or 0),
        "updatedAt": _aware(user.updated_at).isoformat(),
    }


def _snapshot_hash(value: dict[str, Any]) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_renewal_preview(
    session: Session,
    user: PortalUser,
    code_value: str,
    *,
    ttl_minutes: int = 10,
) -> dict[str, Any]:
    try:
        renewal = preview_renewal(session, user, code_value)
    except CodeValidationError as exc:
        raise RenewalPreviewError(str(exc)) from exc
    operation_id = new_id()
    snapshot = _user_snapshot(user)
    payload = {
        **renewal,
        "userSnapshot": snapshot,
    }
    preview = OperationPreview(
        kind="renewal",
        portal_user_id=user.id,
        operation_id=operation_id,
        payload_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        snapshot_hash=_snapshot_hash(snapshot),
        expires_at=utcnow() + timedelta(minutes=max(1, ttl_minutes)),
    )
    session.add(preview)
    session.commit()
    session.refresh(preview)
    return {
        **renewal,
        "previewToken": preview.id,
        "operationId": operation_id,
        "previewExpiresAt": _aware(preview.expires_at).isoformat(),
    }


def validate_renewal_preview(
    session: Session,
    user: PortalUser,
    *,
    preview_token: str,
    operation_id: str,
) -> tuple[OperationPreview, Code, dict[str, Any]]:
    preview = session.get(OperationPreview, preview_token)
    if (
        preview is None
        or preview.kind != "renewal"
        or preview.portal_user_id != user.id
        or preview.operation_id != operation_id
    ):
        raise RenewalPreviewError("invalid renewal preview")
    if preview.consumed_at is not None:
        raise RenewalPreviewError("renewal preview already consumed")
    if _aware(preview.expires_at) <= utcnow():
        raise RenewalPreviewError("renewal preview expired")
    if preview.snapshot_hash != _snapshot_hash(_user_snapshot(user)):
        raise RenewalPreviewError("account state changed; create a new preview")
    try:
        payload = json.loads(preview.payload_json)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RenewalPreviewError("invalid renewal preview") from exc
    code = session.get(Code, str(payload.get("codeId") or ""))
    if code is None:
        raise RenewalPreviewError("renewal code no longer exists")
    try:
        validate_code(session, code.code, username=user.username, action="renew")
    except CodeValidationError as exc:
        raise RenewalPreviewError(str(exc)) from exc
    return preview, code, payload
