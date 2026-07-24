from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import string
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from app.config import Settings
from app.models import AccountOperation, AuditLog, PortalUser, TelegramBindToken, utcnow


class TelegramBindingError(ValueError):
    pass


_CODE_ALPHABET = string.ascii_uppercase + string.digits


def normalize_bind_code(code: str) -> str:
    return code.strip().upper().replace(" ", "")


def hash_bind_code(code: str, *, settings: Settings) -> str:
    normalized = normalize_bind_code(code)
    key = settings.jwt_secret.encode("utf-8")
    return hmac.new(key, normalized.encode("utf-8"), hashlib.sha256).hexdigest()


def _new_bind_code() -> str:
    left = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
    right = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
    return f"TG-{left}-{right}"


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _audit(session: Session, *, action: str, user: PortalUser, detail: dict | None = None) -> None:
    session.add(
        AuditLog(
            actor_user_id=user.id,
            actor_username=user.username,
            action=action,
            target_type="portal_user",
            target_id=user.id,
            detail_json=json.dumps(detail, ensure_ascii=False) if detail else None,
        )
    )


def create_bind_token(
    session: Session,
    user: PortalUser,
    *,
    settings: Settings | None = None,
) -> tuple[str, TelegramBindToken]:
    settings = settings or Settings()
    if user.telegram_id:
        raise TelegramBindingError("Telegram account already bound")

    ttl_minutes = max(1, int(settings.telegram_bind_code_ttl_minutes))
    now = utcnow()
    existing_tokens = session.exec(
        select(TelegramBindToken).where(
            TelegramBindToken.portal_user_id == user.id,
            TelegramBindToken.used_at.is_(None),
        )
    ).all()
    for existing in existing_tokens:
        existing.used_at = now
        session.add(existing)
    expires_at = now + timedelta(minutes=ttl_minutes)
    for _ in range(20):
        code = _new_bind_code()
        code_hash = hash_bind_code(code, settings=settings)
        exists = session.exec(
            select(TelegramBindToken).where(TelegramBindToken.code_hash == code_hash)
        ).first()
        if exists is not None:
            continue
        token = TelegramBindToken(
            portal_user_id=user.id,
            code_hash=code_hash,
            expires_at=expires_at,
        )
        session.add(token)
        _audit(session, action="telegram.bind_token.create", user=user)
        session.commit()
        session.refresh(token)
        token.expires_at = _aware(token.expires_at)
        return code, token
    raise RuntimeError("Failed to generate unique Telegram bind code")


def get_user_by_telegram_id(session: Session, telegram_id: str) -> PortalUser | None:
    normalized = str(telegram_id).strip()
    if not normalized:
        return None
    return session.exec(select(PortalUser).where(PortalUser.telegram_id == normalized)).first()


def _find_token_by_code(session: Session, code: str, *, settings: Settings) -> TelegramBindToken | None:
    code_hash = hash_bind_code(code, settings=settings)
    return session.exec(select(TelegramBindToken).where(TelegramBindToken.code_hash == code_hash)).first()


def bind_telegram_user(
    session: Session,
    *,
    code: str,
    telegram_id: str,
    telegram_username: str | None,
    settings: Settings | None = None,
    operation_id: str | None = None,
) -> PortalUser:
    settings = settings or Settings()
    normalized_telegram_id = str(telegram_id).strip()
    if not normalized_telegram_id:
        raise TelegramBindingError("telegram id is required")

    token = _find_token_by_code(session, code, settings=settings)
    if token is None:
        raise TelegramBindingError("bind code not found")
    idempotency_key = (operation_id or "").strip() or f"telegram-bind:{token.id}"
    replay = session.exec(
        select(AccountOperation).where(
            AccountOperation.idempotency_key == idempotency_key
        )
    ).first()
    if replay is not None:
        if replay.kind != "telegram_binding_activation":
            raise TelegramBindingError("operation id was already used")
        replay_user = (
            session.get(PortalUser, replay.portal_user_id)
            if replay.portal_user_id
            else None
        )
        if replay_user is None or replay_user.telegram_id != normalized_telegram_id:
            raise TelegramBindingError("operation id was already used")
        return replay_user

    existing = get_user_by_telegram_id(session, normalized_telegram_id)
    if existing is not None:
        raise TelegramBindingError("telegram account already bound")

    max_failures = max(1, int(settings.telegram_bind_code_max_failures))
    if token.failed_attempts >= max_failures:
        raise TelegramBindingError("too many failed attempts")
    if token.used_at is not None:
        raise TelegramBindingError("bind code already used")
    if _aware(token.expires_at) <= utcnow():
        raise TelegramBindingError("bind code expired")

    user = session.get(PortalUser, token.portal_user_id)
    if user is None:
        raise TelegramBindingError("portal user not found")
    if user.telegram_id:
        raise TelegramBindingError("portal user already bound")

    user.telegram_id = normalized_telegram_id
    user.telegram_username = (telegram_username or "").strip() or None
    user.telegram_bound_at = utcnow()
    user.updated_at = utcnow()
    token.used_at = utcnow()
    session.add(user)
    session.add(token)
    operation = AccountOperation(
        kind="telegram_binding_activation",
        portal_user_id=user.id,
        idempotency_key=idempotency_key,
        phase="binding_saved",
        request_hash=hashlib.sha256(
            json.dumps(
                {
                    "tokenId": token.id,
                    "telegramId": normalized_telegram_id,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    )
    session.add(operation)
    _audit(
        session,
        action="telegram.bind",
        user=user,
        detail={"telegramUsername": user.telegram_username},
    )
    session.commit()
    session.refresh(user)
    return user


def get_binding_operation(
    session: Session,
    user: PortalUser,
) -> AccountOperation | None:
    return session.exec(
        select(AccountOperation)
        .where(
            AccountOperation.kind == "telegram_binding_activation",
            AccountOperation.portal_user_id == user.id,
        )
        .order_by(AccountOperation.created_at.desc())
    ).first()


def serialize_binding_operation(operation: AccountOperation) -> dict[str, Any]:
    return {
        "operationId": operation.idempotency_key,
        "phase": operation.phase,
        "completed": operation.phase == "completed",
        "retryRequired": operation.phase == "activation_pending",
        "errorCategory": operation.last_error,
    }


async def activate_binding_operation(
    session: Session,
    user: PortalUser,
    *,
    operation: AccountOperation,
    abs_factory: Any,
) -> AccountOperation:
    if operation.portal_user_id != user.id or operation.kind != "telegram_binding_activation":
        raise TelegramBindingError("binding operation does not match user")
    if operation.phase == "completed":
        return operation
    if not user.telegram_binding_required or user.status != "pending":
        operation.phase = "completed"
        operation.status = "completed"
        operation.completed_at = utcnow()
        operation.updated_at = operation.completed_at
        operation.result_json = json.dumps(
            {"status": user.status, "upstreamActivated": True},
            separators=(",", ":"),
        )
        session.add(operation)
        session.commit()
        return operation

    if user.abs_user_id:
        try:
            async with abs_factory() as abs_client:
                await abs_client.update_user(user.abs_user_id, {"isActive": True})
        except Exception as exc:  # noqa: BLE001 - operation remains safely retryable
            operation.phase = "activation_pending"
            operation.status = "pending"
            operation.last_error = type(exc).__name__
            operation.updated_at = utcnow()
            session.add(operation)
            session.commit()
            session.refresh(operation)
            return operation

    now = utcnow()
    if user.expires_at is not None:
        current_expiry = _aware(user.expires_at)
        created_at = _aware(user.created_at)
        if current_expiry is not None:
            user.expires_at = current_expiry + max(now - created_at, timedelta(0))
    user.status = "active"
    user.updated_at = now
    operation.phase = "completed"
    operation.status = "completed"
    operation.last_error = None
    operation.completed_at = now
    operation.updated_at = now
    operation.result_json = json.dumps(
        {"status": "active", "upstreamActivated": True},
        separators=(",", ":"),
    )
    session.add(user)
    session.add(operation)
    session.commit()
    session.refresh(user)
    session.refresh(operation)
    return operation


def unbind_telegram_user(session: Session, user: PortalUser) -> PortalUser:
    user.telegram_id = None
    user.telegram_username = None
    user.telegram_bound_at = None
    user.updated_at = utcnow()
    session.add(user)
    _audit(session, action="telegram.unbind", user=user)
    session.commit()
    session.refresh(user)
    return user
