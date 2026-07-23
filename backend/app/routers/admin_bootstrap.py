import secrets
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import Session, select

from app.config import Settings
from app.db import get_session
from app.models import PortalUser
from app.routers.auth import public_user
from app.security import create_access_token, hash_password
from app.session_cookie import set_session_cookie

router = APIRouter(prefix="/api/admin", tags=["admin"])


class BootstrapAdminRequest(BaseModel):
    username: str = Field(min_length=3, max_length=18, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=6, max_length=18)


def _existing_admin(session: Session) -> PortalUser | None:
    return session.exec(
        select(PortalUser).where(PortalUser.role.in_(["admin", "root"]))
    ).first()


@router.get("/setup-status")
def setup_status(session: Session = Depends(get_session)) -> dict[str, bool]:
    initialized = _existing_admin(session) is not None
    configured = bool(Settings().admin_setup_token)
    return {
        "initialized": initialized,
        "setupAvailable": bool(not initialized and configured),
    }


@router.post("/bootstrap")
def bootstrap_admin(
    payload: BootstrapAdminRequest,
    response: Response,
    setup_token: str | None = Header(default=None, alias="X-Admin-Setup-Token"),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if _existing_admin(session) is not None:
        raise HTTPException(status_code=409, detail="Admin already initialized")
    expected = Settings().admin_setup_token
    if not expected or not setup_token or not secrets.compare_digest(setup_token, expected):
        raise HTTPException(status_code=403, detail="Admin setup token required")
    existing_user = session.exec(select(PortalUser).where(func.lower(PortalUser.username) == payload.username.lower())).first()
    if existing_user is not None:
        raise HTTPException(status_code=409, detail="Username already exists")

    admin = PortalUser(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role="admin",
        status="active",
        abs_user_id="portal-admin-local",
        abs_username=payload.username,
        expires_at=None,
    )
    session.add(admin)
    session.commit()
    session.refresh(admin)
    token = create_access_token(
        subject=admin.id,
        role=admin.role,
        session_version=admin.session_version,
    )
    set_session_cookie(response, token)
    return {"user": public_user(admin)}
