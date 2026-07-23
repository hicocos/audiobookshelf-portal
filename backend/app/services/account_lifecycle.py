from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import HTTPException
from sqlmodel import Session

from app.models import Code, PortalUser, utcnow
from app.services.codes import CodeValidationError, redeem_code, validate_code
from app.services.reconciliation import enqueue_reconciliation_job


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def preview_renewal(session: Session, user: PortalUser, code_value: str) -> dict[str, Any]:
    code = validate_code(session, code_value, username=user.username, action="renew")
    if code.duration_days == 0 and user.expires_at is None and user.status == "active":
        raise CodeValidationError("account already permanent")
    now = utcnow()
    current = _aware(user.expires_at)
    if code.duration_days == 0:
        next_expiry = None
    else:
        base = current if current and current > now else now
        next_expiry = base + timedelta(days=code.duration_days)
    return {
        "codeId": code.id,
        "durationDays": code.duration_days,
        "currentExpiresAt": current.isoformat() if current else None,
        "nextExpiresAt": next_expiry.isoformat() if next_expiry else None,
        "permanent": code.duration_days == 0,
    }


async def renew_user(
    session: Session,
    user: PortalUser,
    code: Code,
    *,
    abs_factory: Any,
) -> dict[str, Any]:
    preview = preview_renewal(session, user, code.code)
    redeemed = redeem_code(
        session,
        code.code,
        username=user.username,
        action="renew",
        commit=False,
        portal_user_id=user.id,
    )
    was_expired = user.status == "expired"
    next_expiry = preview["nextExpiresAt"]
    user.expires_at = datetime.fromisoformat(next_expiry) if next_expiry else None
    if was_expired:
        user.status = "active"
    user.updated_at = utcnow()
    session.add(user)
    session.commit()
    session.refresh(user)

    upstream_reactivated = True
    message = "续期成功，媒体账号已恢复。"
    if was_expired and user.abs_user_id:
        try:
            async with abs_factory() as abs_client:
                await abs_client.update_user(user.abs_user_id, {"isActive": True})
        except (httpx.HTTPError, TypeError, RuntimeError):
            upstream_reactivated = False
            message = "续期已记录，媒体账号正在自动重试恢复；无需重复兑换续期码。"
            enqueue_reconciliation_job(
                session,
                idempotency_key=f"renew:{user.id}:{redeemed.id}",
                operation="set_active",
                target_type="portal_user",
                target_id=user.id,
                abs_user_id=user.abs_user_id,
                payload={"isActive": True, "source": "renew"},
            )
            session.commit()
    return {
        "user": user,
        "redeemedCode": redeemed.code,
        "upstreamReactivated": upstream_reactivated,
        "message": message,
    }


def lifecycle_http_error(exc: CodeValidationError) -> HTTPException:
    detail = str(exc)
    status = 409 if detail == "account already permanent" else 400
    return HTTPException(status_code=status, detail=detail)
