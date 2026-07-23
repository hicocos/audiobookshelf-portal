from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.auth_deps import get_current_claims, get_current_user_from_claims
from app.config import Settings
from app.db import get_session
from app.models import CodeRedemption, MediaRequest, PointLedgerEntry, PortalUser, utcnow
from app.routers.auth import ensure_user_can_login, get_abs_client_factory, public_user
from app.security import create_access_token, hash_password, verify_password
from app.session_cookie import set_session_cookie
from app.services.account_lifecycle import lifecycle_http_error, renew_user
from app.services.capabilities import user_capabilities
from app.services.codes import CodeValidationError, validate_code
from app.services.expiry import disable_upstream_if_expired
from app.services.settings import get_public_settings
from app.services.telegram_binding import TelegramBindingError, create_bind_token, unbind_telegram_user

router = APIRouter(prefix="/api/me", tags=["me"])


class RedeemRequest(BaseModel):
    code: str = Field(min_length=3, max_length=128)


class ChangePasswordRequest(BaseModel):
    currentPassword: str = Field(min_length=1, max_length=256)
    newPassword: str = Field(min_length=1, max_length=18)


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
    return {
        "user": public_user(user),
        "capabilities": user_capabilities(user, get_public_settings(session)),
    }


@router.get("/export")
def export_my_data(
    user: PortalUser = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> JSONResponse:
    redemptions = session.exec(
        select(CodeRedemption)
        .where(CodeRedemption.portal_user_id == user.id)
        .order_by(CodeRedemption.created_at)
    ).all()
    requests = session.exec(
        select(MediaRequest)
        .where(MediaRequest.portal_user_id == user.id)
        .order_by(MediaRequest.created_at)
    ).all()
    points = session.exec(
        select(PointLedgerEntry)
        .where(PointLedgerEntry.portal_user_id == user.id)
        .order_by(PointLedgerEntry.created_at)
    ).all()
    payload = {
        "exportedAt": utcnow(),
        "account": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "status": user.status,
            "expiresAt": user.expires_at,
            "createdAt": user.created_at,
            "lastLoginAt": user.last_login_at,
            "passwordChangedAt": user.password_changed_at,
            "telegramId": user.telegram_id,
            "telegramUsername": user.telegram_username,
            "telegramBoundAt": user.telegram_bound_at,
        },
        "codeRedemptions": redemptions,
        "mediaRequests": requests,
        "pointHistory": points,
        "notIncluded": [
            "password hashes and reset tokens",
            "administrator security audit records",
            "Audiobookshelf listening activity; request it from the service operator",
        ],
    }
    return JSONResponse(
        content=jsonable_encoder(payload),
        headers={
            "Content-Disposition": (
                f'attachment; filename="moyin-data-{user.username}-{utcnow().date().isoformat()}.json"'
            )
        },
    )


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
    if user.telegram_binding_required:
        raise HTTPException(status_code=409, detail="此账号必须绑定 Telegram，不能自行解绑。")
    user = unbind_telegram_user(session, user)
    return {"ok": True, "user": public_user(user)}


@router.post("/redeem")
async def redeem(
    payload: RedeemRequest,
    user: PortalUser = Depends(get_current_user),
    session: Session = Depends(get_session),
    abs_factory: Any = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    capabilities = user_capabilities(user, get_public_settings(session))
    if not capabilities["canRenew"]:
        raise HTTPException(
            status_code=403,
            detail=capabilities["unavailableReasons"].get("renew", "续期功能当前未开放。"),
        )
    try:
        code = validate_code(session, payload.code, username=user.username, action="renew")
        result = await renew_user(session, user, code, abs_factory=abs_factory)
    except CodeValidationError as exc:
        raise lifecycle_http_error(exc) from exc

    return {
        "user": public_user(result["user"]),
        "redeemedCode": result["redeemedCode"],
        "upstreamReactivated": result["upstreamReactivated"],
        "message": result["message"],
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
