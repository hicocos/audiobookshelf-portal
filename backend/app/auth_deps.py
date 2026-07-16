from typing import Any

from fastapi import Depends, Header, HTTPException, Request
from sqlmodel import Session

from app.config import Settings
from app.db import get_session
from app.models import PortalUser
from app.security import decode_access_token


def _extract_bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1]
    return None


def get_current_claims(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    settings = Settings()
    token = _extract_bearer(authorization) or request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="Missing session")
    try:
        return decode_access_token(token, settings=settings)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc


def get_current_user_from_claims(
    claims: dict[str, Any],
    session: Session,
) -> PortalUser:
    subject = claims.get("sub")
    if not subject:
        raise HTTPException(status_code=401, detail="Invalid session")
    user = session.get(PortalUser, subject)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid session")
    try:
        token_version = int(claims.get("sv", -1))
    except (TypeError, ValueError):
        token_version = -1
    if token_version != int(user.session_version or 0):
        raise HTTPException(status_code=401, detail="Session revoked")
    return user


def require_admin(
    request: Request,
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    claims = get_current_claims(request=request, authorization=authorization)
    if claims.get("role") not in {"admin", "root"}:
        raise HTTPException(status_code=403, detail="Admin role required")
    user = get_current_user_from_claims(claims, session)
    if user.status != "active" or user.role not in {"admin", "root"}:
        raise HTTPException(status_code=403, detail="Admin role required")
    claims["role"] = user.role
    claims["username"] = user.username
    return claims
