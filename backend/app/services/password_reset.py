import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlmodel import Session, select

from app.config import Settings
from app.models import AuditLog, PasswordResetToken, PortalUser, utcnow
from app.security import hash_password


class PasswordResetError(ValueError):
    pass


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_password_reset_token(
    session: Session,
    user: PortalUser,
    *,
    settings: Settings | None = None,
) -> tuple[str, PasswordResetToken]:
    settings = settings or Settings()
    if user.status not in {"active", "expired"}:
        raise PasswordResetError("account is not eligible for password reset")
    now = utcnow()
    existing = session.exec(
        select(PasswordResetToken).where(
            PasswordResetToken.portal_user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
    ).all()
    for item in existing:
        item.used_at = now
        session.add(item)
    raw = secrets.token_urlsafe(32)
    ttl = max(1, int(settings.telegram_password_reset_ttl_minutes))
    token = PasswordResetToken(
        portal_user_id=user.id,
        token_hash=_token_hash(raw),
        expires_at=now + timedelta(minutes=ttl),
    )
    session.add(token)
    session.add(
        AuditLog(
            actor_user_id=user.id,
            actor_username=user.username,
            action="telegram.password_reset.create",
            target_type="portal_user",
            target_id=user.id,
        )
    )
    session.commit()
    session.refresh(token)
    return raw, token


def get_valid_reset(
    session: Session,
    raw_token: str,
) -> tuple[PasswordResetToken, PortalUser]:
    if len(raw_token) < 32:
        raise PasswordResetError("invalid password reset token")
    token = session.exec(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == _token_hash(raw_token)
        )
    ).first()
    if token is None or token.used_at is not None or _aware(token.expires_at) <= utcnow():
        raise PasswordResetError("invalid or expired password reset token")
    user = session.get(PortalUser, token.portal_user_id)
    if user is None or user.status not in {"active", "expired"}:
        raise PasswordResetError("account is not eligible for password reset")
    return token, user


async def reset_password(
    session: Session,
    *,
    raw_token: str,
    new_password: str,
    abs_factory: Any,
    settings: Settings | None = None,
) -> PortalUser:
    settings = settings or Settings()
    token, user = get_valid_reset(session, raw_token)
    min_length = max(1, int(settings.portal_password_min_length))
    if len(new_password) < min_length:
        raise PasswordResetError(f"password must be at least {min_length} characters")
    if user.abs_user_id:
        try:
            async with abs_factory() as abs_client:
                await abs_client.update_user(user.abs_user_id, {"password": new_password})
        except (httpx.HTTPError, TypeError, RuntimeError) as exc:
            raise PasswordResetError("media server unavailable; password not changed") from exc
    now = utcnow()
    user.password_hash = hash_password(new_password)
    user.password_changed_at = now
    user.session_version = int(user.session_version or 0) + 1
    user.updated_at = now
    token.used_at = now
    session.add(user)
    session.add(token)
    session.add(
        AuditLog(
            actor_user_id=user.id,
            actor_username=user.username,
            action="telegram.password_reset.consume",
            target_type="portal_user",
            target_id=user.id,
            detail_json=json.dumps({"tokenId": token.id}),
        )
    )
    session.commit()
    session.refresh(user)
    return user
