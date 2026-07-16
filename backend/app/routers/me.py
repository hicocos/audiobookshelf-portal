from datetime import UTC, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.abs_client import AudiobookshelfClient
from app.auth_deps import get_current_claims, get_current_user_from_claims
from app.config import Settings
from app.db import get_session
from app.models import Code, PortalUser, ReconciliationJob, utcnow
from app.routers.auth import ensure_user_can_login, get_abs_client_factory, public_user
from app.security import create_access_token, hash_password, verify_password
from app.session_cookie import set_session_cookie
from app.services.codes import CodeValidationError, redeem_code
from app.services.expiry import disable_upstream_if_expired
from app.services.reconciliation import enqueue_reconciliation_job
from app.services.telegram_binding import TelegramBindingError, create_bind_token, unbind_telegram_user

router = APIRouter(prefix="/api/me", tags=["me"])


class RedeemRequest(BaseModel):
    code: str = Field(min_length=3, max_length=128)


class ChangePasswordRequest(BaseModel):
    currentPassword: str = Field(min_length=1, max_length=256)
    newPassword: str = Field(min_length=1, max_length=256)


def get_current_user(
    claims: dict[str, Any] = Depends(get_current_claims),
    session: Session = Depends(get_session),
) -> PortalUser:
    user = get_current_user_from_claims(claims, session)
    ensure_user_can_login(user, session)
    return user


async def sync_upstream_account_status(
    user: PortalUser,
    session: Session,
    abs_factory: Any,
) -> PortalUser:
    # Admins are portal-native accounts and may not have a matching upstream
    # media-server user. Never let upstream reconciliation flip an admin to
    # disabled/deleted, which would corrupt their account state.
    if user.role in {"admin", "root"}:
        return user
    if not user.abs_user_id:
        return user
    try:
        async with abs_factory() as abs_client:
            upstream_users = await abs_client.list_users()
    except (httpx.HTTPError, TypeError, RuntimeError):
        return user

    upstream_user = next((item for item in upstream_users if item.get("id") == user.abs_user_id), None)
    if upstream_user is None:
        if user.status != "deleted":
            user.status = "deleted"
            user.session_version = int(user.session_version or 0) + 1
            session.add(user)
            session.commit()
            session.refresh(user)
        return user

    if upstream_user.get("isActive") is False and user.status == "active":
        user.status = "disabled"
        user.session_version = int(user.session_version or 0) + 1
        session.add(user)
        session.commit()
        session.refresh(user)
    elif upstream_user.get("isActive") is True and user.status in {"deleted", "disabled"}:
        user.status = "active"
        session.add(user)
        session.commit()
        session.refresh(user)
    return user


@router.get("")
async def me(
    user: PortalUser = Depends(get_current_user),
    session: Session = Depends(get_session),
    abs_factory: Any = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    # If the member has naturally expired, revoke upstream media access right
    # now rather than waiting for the background worker's next tick.
    await disable_upstream_if_expired(user, session, abs_factory)
    user = await sync_upstream_account_status(user, session, abs_factory)
    return {"user": public_user(user)}


@router.post("/telegram/bind-token")
def create_telegram_bind_token(
    user: PortalUser = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        code, token = create_bind_token(session, user, settings=Settings())
    except TelegramBindingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    settings = Settings()
    return {
        "code": code,
        "expiresAt": token.expires_at.isoformat(),
        "botUsername": settings.telegram_bot_username or None,
        "command": f"/bind {code}",
    }


@router.delete("/telegram/binding")
def delete_telegram_binding(
    user: PortalUser = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    user = unbind_telegram_user(session, user)
    return {"ok": True, "user": public_user(user)}


@router.post("/redeem")
async def redeem(
    payload: RedeemRequest,
    user: PortalUser = Depends(get_current_user),
    session: Session = Depends(get_session),
    abs_factory: Any = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    # Peek at the code first (purpose + duration) so we can short-circuit the
    # "already permanent + permanent renewal code" case WITHOUT consuming a use.
    # The user is already on a lifetime plan, so applying a permanent code would
    # be a no-op that silently wastes the code — instead we reject and the
    # frontend shows a popup explaining the account is already permanent.
    normalized = payload.code.strip().upper()
    peek = session.exec(select(Code).where(Code.code == normalized)).first()
    if (
        peek is not None
        and peek.status == "active"
        and peek.type == "renew"
        and peek.duration_days == 0
        and user.expires_at is None
        and user.status == "active"
    ):
        raise HTTPException(status_code=409, detail="account already permanent")

    try:
        code = redeem_code(session, payload.code, username=user.username, action="renew")
    except CodeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    was_expired = user.status == "expired"
    if code.duration_days == 0:
        user.expires_at = None
    else:
        now = utcnow()
        current_expiry = user.expires_at
        if current_expiry is not None and current_expiry.tzinfo is None:
            current_expiry = current_expiry.replace(tzinfo=UTC)
        base = current_expiry if current_expiry and current_expiry > now else now
        user.expires_at = base + timedelta(days=code.duration_days)
    if user.status == "expired":
        user.status = "active"
    session.add(user)
    session.commit()
    session.refresh(user)

    upstream_reactivated = True
    upstream_message = "续期成功，媒体账号已恢复。"
    if was_expired and user.status == "active" and user.abs_user_id:
        try:
            async with abs_factory() as abs_client:
                await abs_client.update_user(user.abs_user_id, {"isActive": True})
        except (httpx.HTTPError, TypeError, RuntimeError) as exc:
            upstream_reactivated = False
            upstream_message = "续期已记录，媒体账号正在自动重试恢复；无需重复兑换续期码。"
            enqueue_reconciliation_job(
                session,
                idempotency_key=f"renew:{user.id}:{code.id}",
                operation="set_active",
                target_type="portal_user",
                target_id=user.id,
                abs_user_id=user.abs_user_id,
                payload={"isActive": True, "source": "renew"},
            )
            session.commit()

    return {
        "user": public_user(user),
        "redeemedCode": code.code,
        "upstreamReactivated": upstream_reactivated,
        "message": upstream_message,
    }


@router.post("/password")
async def change_password(
    payload: ChangePasswordRequest,
    response: Response,
    user: PortalUser = Depends(get_current_user),
    session: Session = Depends(get_session),
    abs_factory: Any = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    # Self-service password change. The member must prove they know their current
    # password before we accept a new one — this is the user-facing equivalent of
    # the admin set_password endpoint, minus the privileged override.
    if not verify_password(payload.currentPassword, user.password_hash):
        raise HTTPException(status_code=400, detail="当前密码不正确。")

    min_length = max(1, int(Settings().portal_password_min_length))
    if len(payload.newPassword) < min_length:
        raise HTTPException(status_code=422, detail=f"密码至少需要 {min_length} 位字符。")

    if payload.newPassword == payload.currentPassword:
        raise HTTPException(status_code=400, detail="新密码不能与当前密码相同。")

    # Sync to the upstream media server FIRST. If ABS rejects the change we abort
    # and leave the local password untouched, so the portal and the listening app
    # never drift out of sync. Only after upstream succeeds do we persist locally.
    if user.abs_user_id:
        try:
            async with abs_factory() as abs_client:
                await abs_client.update_user(user.abs_user_id, {"password": payload.newPassword})
        except (httpx.HTTPError, TypeError, RuntimeError) as exc:
            raise HTTPException(
                status_code=502,
                detail="媒体服务器暂时不可用，密码未修改，请稍后重试。",
            ) from exc

    user.password_hash = hash_password(payload.newPassword)
    user.password_changed_at = utcnow()
    user.session_version = int(user.session_version or 0) + 1
    user.updated_at = utcnow()
    session.add(user)
    session.commit()
    session.refresh(user)
    token = create_access_token(
        subject=user.id,
        role=user.role,
        session_version=user.session_version,
    )
    set_session_cookie(response, token, settings=Settings())
    return {"user": public_user(user)}
