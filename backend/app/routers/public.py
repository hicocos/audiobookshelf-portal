import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlmodel import Session

from app.auth_deps import get_current_claims, get_current_user_from_claims
from app.config import Settings
from app.db import get_session
from app.observability import set_dependency_ready
from app.routers.auth import get_abs_client_factory
from app.services.settings import get_public_settings
from app.services.password_reset import (
    PasswordResetError,
    get_valid_reset,
    reset_password,
)

router = APIRouter()


class PasswordResetRequest(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    newPassword: str = Field(min_length=1, max_length=18)


class PasswordResetValidationRequest(BaseModel):
    token: str = Field(min_length=32, max_length=256)


@router.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@router.get("/version")
def version() -> dict[str, str]:
    return {
        "version": os.getenv("BUILD_VERSION", "dev"),
        "commit": os.getenv("BUILD_COMMIT", "unknown"),
        "builtAt": os.getenv("BUILD_DATE", "unknown"),
    }


@router.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/health/ready")
async def health_ready(
    session: Session = Depends(get_session),
    abs_factory: Any = Depends(get_abs_client_factory),
) -> dict[str, str]:
    status = {"database": "ok", "audiobookshelf": "ok"}
    try:
        session.exec(text("SELECT 1")).one()
    except Exception as exc:  # noqa: BLE001 - readiness must convert DB faults to 503
        status["database"] = "unavailable"
        set_dependency_ready("database", False)
        raise HTTPException(status_code=503, detail=status) from exc
    set_dependency_ready("database", True)
    try:
        async with abs_factory() as abs_client:
            if not await abs_client.ping():
                raise RuntimeError("ABS ping failed")
    except Exception as exc:  # noqa: BLE001 - readiness must convert upstream faults to 503
        status["audiobookshelf"] = "unavailable"
        set_dependency_ready("audiobookshelf", False)
        raise HTTPException(status_code=503, detail=status) from exc
    set_dependency_ready("audiobookshelf", True)
    return {"status": "ready", **status}


@router.get("/config")
def public_config(session: Session = Depends(get_session)) -> dict[str, Any]:
    settings = Settings()
    public_settings = get_public_settings(session)
    public_settings["features"]["registration"] = bool(settings.registration_enabled and public_settings["features"].get("registration", True))
    public_settings["registrationEnabled"] = public_settings["features"]["registration"]
    public_settings["passwordMinLength"] = max(1, int(settings.portal_password_min_length))
    telegram = public_settings.get("telegram")
    if isinstance(telegram, dict):
        telegram["botUsername"] = settings.telegram_bot_username or None
    return public_settings


@router.post("/password-reset/validate")
def validate_password_reset(
    payload: PasswordResetValidationRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        reset_token, user = get_valid_reset(session, payload.token)
    except PasswordResetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "valid": True,
        "username": user.username,
        "expiresAt": reset_token.expires_at.isoformat(),
        "passwordMinLength": max(1, int(Settings().portal_password_min_length)),
    }


@router.post("/password-reset")
async def consume_password_reset(
    payload: PasswordResetRequest,
    session: Session = Depends(get_session),
    abs_factory: Any = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    try:
        user = await reset_password(
            session,
            raw_token=payload.token,
            new_password=payload.newPassword,
            abs_factory=abs_factory,
        )
    except PasswordResetError as exc:
        detail = str(exc)
        status = 502 if detail.startswith("media server unavailable") else 400
        raise HTTPException(status_code=status, detail=detail) from exc
    return {"ok": True, "username": user.username}


@router.get("/session-status")
def session_status(request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Lightweight public auth probe that keeps anonymous homepage visits out of 401 logs."""
    try:
        claims = get_current_claims(request=request, authorization=None)
        user = get_current_user_from_claims(claims, session)
    except Exception:
        return {"authenticated": False, "admin": False}

    if user is None:
        return {"authenticated": False, "admin": False}

    return {
        "authenticated": True,
        "admin": user.role in {"admin", "root"} and user.status == "active",
        "accountStatus": user.status,
        "status": user.status,
        "role": user.role,
    }
