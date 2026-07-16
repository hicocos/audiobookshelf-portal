from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlmodel import Session

from app.auth_deps import get_current_claims, get_current_user_from_claims
from app.config import Settings
from app.db import get_session
from app.observability import set_dependency_ready
from app.routers.auth import get_abs_client_factory
from app.services.settings import get_public_settings

router = APIRouter()


@router.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


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
    return public_settings


@router.get("/session-status")
def session_status(request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Lightweight public auth probe that keeps anonymous homepage visits out of 401 logs."""
    try:
        claims = get_current_claims(request=request, authorization=None)
        user = get_current_user_from_claims(claims, session)
    except Exception:
        return {"authenticated": False, "admin": False}

    if user is None or user.status not in {"active", "expired"}:
        return {"authenticated": False, "admin": False}

    return {
        "authenticated": True,
        "admin": user.role in {"admin", "root"} and user.status == "active",
        "status": user.status,
        "role": user.role,
    }
