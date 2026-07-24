import json
from typing import Any

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import func
from sqlmodel import Session, select

from app.config import Settings
from app.db import get_session
from app.models import AuditLog, PortalUser
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


def require_root(
    request: Request,
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    claims = require_admin(
        request=request,
        authorization=authorization,
        session=session,
    )
    if claims.get("role") != "root":
        raise HTTPException(status_code=403, detail="Root role required")
    claims["capabilityMode"] = "root_enforced"
    return claims


def require_root_for_high_risk(
    request: Request,
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Enforce root once one exists, with an audited no-root migration bridge.

    Production currently has no root account. Immediately making these routes
    strictly root-only would lock out all operations, so the temporary bridge
    remains explicit and self-disabling as soon as an active root is present.
    """

    claims = require_admin(
        request=request,
        authorization=authorization,
        session=session,
    )
    if claims.get("role") == "root":
        claims["capabilityMode"] = "root_enforced"
        return claims
    active_roots = int(
        session.exec(
            select(func.count(PortalUser.id)).where(
                PortalUser.role == "root",
                PortalUser.status == "active",
            )
        ).one()
    )
    action = (
        "capability.high_risk.denied"
        if active_roots
        else "capability.high_risk.legacy_admin_fallback"
    )
    session.add(
        AuditLog(
            actor_user_id=str(claims.get("sub") or "") or None,
            actor_username=str(claims.get("username") or "admin"),
            action=action,
            target_type="capability",
            target_id="high_risk",
            detail_json=json.dumps(
                {
                    "activeRootCount": active_roots,
                    "mode": "root_enforced" if active_roots else "audit_only_no_root",
                },
                separators=(",", ":"),
            ),
        )
    )
    session.commit()
    if active_roots:
        raise HTTPException(status_code=403, detail="Root role required")
    claims["capabilityMode"] = "audit_only_no_root"
    return claims
