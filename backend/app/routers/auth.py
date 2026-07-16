from collections.abc import Callable
from datetime import UTC, timedelta
from functools import lru_cache
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import Session, select

from app.abs_client import AudiobookshelfClient
from app.config import Settings
from app.db import get_session
from app.models import PortalUser, utcnow
from app.rate_limit import login_ip_limiter, login_limiter
from app.security import create_access_token, hash_password, verify_password
from app.session_cookie import clear_session_cookie, set_session_cookie
from app.services.codes import CodeValidationError, redeem_code
from app.services.settings import get_public_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=256)
    inviteCode: str = Field(min_length=3, max_length=128)
    email: str | None = None


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


def _aware_datetime(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _aware_expiry(user: PortalUser):
    return _aware_datetime(user.expires_at)


def is_user_expired(user: PortalUser) -> bool:
    expires_at = _aware_expiry(user)
    return bool(expires_at and expires_at <= utcnow())


def public_user(user: PortalUser) -> dict[str, Any]:
    expires_at = _aware_expiry(user)
    telegram_bound_at = _aware_datetime(user.telegram_bound_at)
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "status": user.status,
        "expiresAt": expires_at.isoformat() if expires_at else None,
        "telegramBound": bool(user.telegram_id),
        "telegramUsername": user.telegram_username,
        "telegramBoundAt": telegram_bound_at.isoformat() if telegram_bound_at else None,
    }


def ensure_user_can_login(user: PortalUser, session: Session) -> None:
    # Admins are never locked out by expiry/status so they can always manage the portal.
    if user.role in {"admin", "root"}:
        return
    # Expired users are allowed INTO the portal so they can redeem a renewal code.
    # Their media access is revoked separately by disabling the upstream
    # Audiobookshelf account (see services/expiry.sync_expired_users). We only
    # mark the local status as expired here; we do NOT block the portal session.
    if is_user_expired(user):
        if user.status not in ("expired", "disabled", "deleted"):
            user.status = "expired"
            user.session_version = int(user.session_version or 0) + 1
            user.updated_at = utcnow()
            session.add(user)
            session.commit()
    # Disabled / deleted accounts are fully blocked from the portal.
    if user.status in ("disabled", "deleted"):
        raise HTTPException(status_code=403, detail="Account is not active")


def default_abs_permissions() -> dict[str, bool]:
    return {
        "download": False,
        "update": False,
        "delete": False,
        "upload": False,
        "createEreader": False,
        "accessAllLibraries": True,
        "accessAllTags": True,
        "accessExplicitContent": True,
        "selectedTagsNotAccessible": False,
    }


@lru_cache(maxsize=None)
def _shared_abs_client(base_url: str, token: str) -> AudiobookshelfClient:
    return AudiobookshelfClient(base_url, token, keep_open=True)


def get_abs_client_factory() -> Callable[[], AudiobookshelfClient]:
    settings = Settings()
    client = _shared_abs_client(
        settings.audiobookshelf_url,
        settings.audiobookshelf_admin_token,
    )
    return lambda: client


@router.post("/register")
async def register(
    payload: RegisterRequest,
    response: Response,
    session: Session = Depends(get_session),
    abs_factory: Callable[[], AudiobookshelfClient] = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    # Respect the admin "registration" feature toggle on the server side.
    # The frontend hides the form when it's off, but that is cosmetic only —
    # without this check a direct POST with a valid invite code would bypass it.
    public_settings = get_public_settings(session)
    if public_settings.get("features", {}).get("registration", True) is False:
        raise HTTPException(status_code=403, detail="当前暂未开放自助注册，请联系管理员。")

    # Match usernames case-insensitively so "MoYking" and "moyking" are the same
    # account, mirroring Audiobookshelf's case-insensitive usernames and preventing
    # near-duplicate registrations that differ only by letter case.
    existing = session.exec(
        select(PortalUser).where(func.lower(PortalUser.username) == payload.username.lower())
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Username already exists")

    settings = Settings()
    min_password_length = max(1, int(settings.portal_password_min_length))
    if len(payload.password) < min_password_length:
        raise HTTPException(status_code=422, detail=f"Password must be at least {min_password_length} characters")

    try:
        code = redeem_code(
            session,
            payload.inviteCode,
            username=payload.username,
            action="register",
            commit=False,
        )
    except CodeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        async with abs_factory() as abs_client:
            abs_user = await abs_client.create_user(
                username=payload.username,
                password=payload.password,
                permissions=default_abs_permissions(),
                is_active=True,
            )
    except (httpx.HTTPError, TypeError, RuntimeError, KeyError) as exc:
        session.rollback()
        raise HTTPException(
            status_code=502,
            detail="Upstream media server user creation failed. Please contact the administrator.",
        ) from exc

    expires_at = None if code.duration_days == 0 else utcnow() + timedelta(days=code.duration_days)
    user = PortalUser(
        username=payload.username,
        password_hash=hash_password(payload.password),
        email=payload.email,
        abs_user_id=abs_user["id"],
        abs_username=abs_user.get("username", payload.username),
        expires_at=expires_at,
    )
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


def _client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    trusted = {
        item.strip()
        for item in Settings().trusted_proxy_ips.split(",")
        if item.strip()
    }
    if peer in trusted:
        forwarded = request.headers.get("x-forwarded-for", "")
        candidate = forwarded.split(",")[0].strip()
        if candidate:
            return candidate
    return peer


def _client_key(client_ip: str, username: str) -> str:
    return f"{client_ip}|{username.lower()}"


@router.post("/login")
async def login(payload: LoginRequest, request: Request, response: Response, session: Session = Depends(get_session), abs_factory: Callable[[], AudiobookshelfClient] = Depends(get_abs_client_factory)) -> dict[str, Any]:
    client_ip = _client_ip(request)
    rl_key = _client_key(client_ip, payload.username)
    if not login_ip_limiter.allow(client_ip) or not login_limiter.allow(rl_key):
        retry_after = max(
            login_ip_limiter.retry_after(client_ip),
            login_limiter.retry_after(rl_key),
        )
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )
    # Case-insensitive username lookup: the portal must not reject a valid member
    # just because they typed their name with different capitalization than at
    # registration (the upstream ABS app already treats usernames case-insensitively).
    user = session.exec(
        select(PortalUser).where(func.lower(PortalUser.username) == payload.username.lower())
    ).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        login_limiter.register_failure(rl_key)
        login_ip_limiter.register_failure(client_ip)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    ensure_user_can_login(user, session)
    login_limiter.reset(rl_key)
    # Naturally expired members are allowed into the portal to renew, but their
    # upstream media access is revoked immediately on login rather than waiting
    # for the background worker.
    from app.services.expiry import disable_upstream_if_expired

    await disable_upstream_if_expired(user, session, abs_factory)
    user.last_login_at = utcnow()
    session.add(user)
    session.commit()
    token = create_access_token(
        subject=user.id,
        role=user.role,
        session_version=user.session_version,
    )
    set_session_cookie(response, token, settings=Settings())
    return {"user": public_user(user)}


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    clear_session_cookie(response, settings=Settings())
    return {"ok": True}
