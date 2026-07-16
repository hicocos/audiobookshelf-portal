import secrets
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from app.config import Settings
from app.db import get_session
from app.internal_auth import require_internal_bot
from app.models import PortalUser, utcnow
from app.routers.auth import default_abs_permissions, ensure_user_can_login, get_abs_client_factory
from app.routers.library import _allowed_library_ids, _public_item, _public_library
from app.security import hash_password
from app.services.codes import CodeValidationError, redeem_code, validate_code
from app.services.settings import get_public_settings
from app.services.telegram_binding import TelegramBindingError, bind_telegram_user, get_user_by_telegram_id

router = APIRouter(
    prefix="/api/internal/tg",
    tags=["internal-tg"],
    dependencies=[Depends(require_internal_bot)],
)
logger = logging.getLogger(__name__)


class BindRequest(BaseModel):
    code: str = Field(min_length=3, max_length=128)
    telegramId: str = Field(min_length=1, max_length=64)
    telegramUsername: str | None = Field(default=None, max_length=128)


class TelegramIdRequest(BaseModel):
    telegramId: str = Field(min_length=1, max_length=64)


class RegisterRequest(BaseModel):
    telegramId: str = Field(min_length=1, max_length=64)
    telegramUsername: str | None = Field(default=None, max_length=128)
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    inviteCode: str = Field(min_length=3, max_length=128)


class InviteCheckRequest(BaseModel):
    telegramId: str = Field(min_length=1, max_length=64)
    inviteCode: str = Field(min_length=3, max_length=128)


class UsernameCheckRequest(BaseModel):
    telegramId: str = Field(min_length=1, max_length=64)
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    inviteCode: str = Field(min_length=3, max_length=128)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _server_url() -> str:
    # Public ABS/server address shown to members is configured in AppSetting.
    # Avoid importing settings service here to keep this internal API small; the
    # bot mainly needs a stable portal URL fallback.
    return Settings().portal_public_url.rstrip("/")


def _internal_user(user: PortalUser) -> dict[str, Any]:
    expires_at = _aware(user.expires_at)
    bound_at = _aware(user.telegram_bound_at)
    return {
        "id": user.id,
        "username": user.username,
        "status": user.status,
        "role": user.role,
        "expiresAt": expires_at.isoformat() if expires_at else None,
        "absUserId": user.abs_user_id,
        "absUsername": user.abs_username,
        "telegramUsername": user.telegram_username,
        "telegramBoundAt": bound_at.isoformat() if bound_at else None,
    }


def _bound_response(user: PortalUser) -> dict[str, Any]:
    return {"bound": True, "user": _internal_user(user), "serverUrl": _server_url()}


def _bound_user_or_404(session: Session, telegram_id: str) -> PortalUser:
    user = get_user_by_telegram_id(session, telegram_id)
    if user is None:
        raise HTTPException(status_code=404, detail="telegram account is not bound")
    return user


def _new_initial_password() -> str:
    return secrets.token_urlsafe(12)


def _ensure_public_registration_allowed(session: Session, telegram_id: str) -> None:
    public_settings = get_public_settings(session)
    if public_settings.get("features", {}).get("registration", True) is False:
        raise HTTPException(status_code=403, detail="registration is currently disabled")
    if get_user_by_telegram_id(session, telegram_id.strip()) is not None:
        raise HTTPException(status_code=409, detail="telegram account already bound")


def _existing_active_username(session: Session, username: str) -> PortalUser | None:
    existing = session.exec(
        select(PortalUser).where(func.lower(PortalUser.username) == username.lower())
    ).first()
    if existing and existing.status != "deleted":
        return existing
    return None


@router.post("/register/invite/check")
def check_register_invite(payload: InviteCheckRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    _ensure_public_registration_allowed(session, payload.telegramId)
    try:
        code = validate_code(session, payload.inviteCode, action="register")
    except CodeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "durationDays": code.duration_days,
        "remainingUses": max(0, code.max_uses - code.used_count),
        "designatedUsername": code.designated_username,
    }


@router.post("/register/username/check")
def check_register_username(payload: UsernameCheckRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    _ensure_public_registration_allowed(session, payload.telegramId)
    try:
        code = validate_code(session, payload.inviteCode, username=payload.username, action="register")
    except CodeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if _existing_active_username(session, payload.username) is not None:
        raise HTTPException(status_code=409, detail="username already exists")
    return {
        "ok": True,
        "username": payload.username,
        "durationDays": code.duration_days,
    }


@router.post("/register")
async def register(
    payload: RegisterRequest,
    session: Session = Depends(get_session),
    abs_factory: Any = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    settings = Settings()
    telegram_id = payload.telegramId.strip()
    _ensure_public_registration_allowed(session, telegram_id)

    existing = session.exec(
        select(PortalUser).where(func.lower(PortalUser.username) == payload.username.lower())
    ).first()
    if existing and existing.status != "deleted":
        raise HTTPException(status_code=409, detail="username already exists")

    password = _new_initial_password()
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
                password=password,
                permissions=default_abs_permissions(),
                is_active=True,
            )
    except (httpx.HTTPError, TypeError, RuntimeError, KeyError) as exc:
        session.rollback()
        raise HTTPException(status_code=502, detail="upstream media server user creation failed") from exc

    expires_at = None if code.duration_days == 0 else utcnow() + timedelta(days=code.duration_days)
    if existing is not None:
        user = existing
        user.password_hash = hash_password(password)
        user.abs_user_id = abs_user["id"]
        user.abs_username = abs_user.get("username", payload.username)
        user.sync_normalized_usernames()
        user.expires_at = expires_at
        user.status = "active"
        user.role = "user" if user.role == "admin" else user.role
    else:
        user = PortalUser(
            username=payload.username,
            password_hash=hash_password(password),
            abs_user_id=abs_user["id"],
            abs_username=abs_user.get("username", payload.username),
            expires_at=expires_at,
        )
    user.telegram_id = telegram_id
    user.telegram_username = (payload.telegramUsername or "").strip() or None
    user.telegram_bound_at = utcnow()
    user.updated_at = utcnow()
    session.add(user)
    try:
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        try:
            async with abs_factory() as abs_client:
                await abs_client.delete_user(str(abs_user["id"]))
        except Exception:  # noqa: BLE001 - log all failed compensation attempts
            logger.exception(
                "Failed to compensate ABS user after Telegram registration conflict abs_user_id=%s",
                abs_user.get("id"),
            )
        raise HTTPException(status_code=409, detail="username or telegram account already exists") from exc
    session.refresh(user)
    return {"created": True, "oneTimePassword": password, **_bound_response(user)}


@router.post("/bind")
def bind(payload: BindRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        user = bind_telegram_user(
            session,
            code=payload.code,
            telegram_id=payload.telegramId,
            telegram_username=payload.telegramUsername,
            settings=Settings(),
        )
    except TelegramBindingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _bound_response(user)


@router.get("/me/{telegram_id}")
def me(telegram_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    user = get_user_by_telegram_id(session, telegram_id)
    if user is None:
        return {"bound": False}
    return _bound_response(user)


@router.post("/open")
def open_account(payload: TelegramIdRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    user = _bound_user_or_404(session, payload.telegramId)
    ensure_user_can_login(user, session)
    if user.abs_user_id:
        return {"opened": True, "alreadyOpen": True, **_bound_response(user)}
    raise HTTPException(
        status_code=409,
        detail="portal account is missing an ABS account; please reset password in the web dashboard first",
    )


async def _library_context(user: PortalUser, abs_factory: Any) -> tuple[list[dict[str, Any]], set[str] | None]:
    try:
        async with abs_factory() as abs_client:
            all_libraries = await abs_client.list_libraries()
            upstream_user = await abs_client.get_user(user.abs_user_id) if user.abs_user_id else {}
            allowed_ids = _allowed_library_ids(upstream_user if isinstance(upstream_user, dict) else {})
            libraries = all_libraries if allowed_ids is None else [
                item for item in all_libraries if str(item.get("id") or "") in allowed_ids
            ]
            return libraries, allowed_ids
    except (httpx.HTTPError, TypeError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail="media library is temporarily unavailable") from exc


@router.get("/library/summary/{telegram_id}")
async def library_summary(
    telegram_id: str,
    session: Session = Depends(get_session),
    abs_factory: Any = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    user = _bound_user_or_404(session, telegram_id)
    ensure_user_can_login(user, session)
    libraries, _allowed_ids = await _library_context(user, abs_factory)
    return {"bound": True, "libraries": [_public_library(item) for item in libraries], "count": len(libraries)}


@router.get("/library/search/{telegram_id}")
async def library_search(
    telegram_id: str,
    q: str = Query(min_length=1, max_length=100),
    limit: int = 8,
    session: Session = Depends(get_session),
    abs_factory: Any = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    user = _bound_user_or_404(session, telegram_id)
    ensure_user_can_login(user, session)
    settings = Settings()
    safe_limit = max(1, min(int(limit or settings.telegram_search_result_limit), 20))

    try:
        async with abs_factory() as abs_client:
            all_libraries = await abs_client.list_libraries()
            upstream_user = await abs_client.get_user(user.abs_user_id) if user.abs_user_id else {}
            allowed_ids = _allowed_library_ids(upstream_user if isinstance(upstream_user, dict) else {})
            libraries = all_libraries if allowed_ids is None else [
                item for item in all_libraries if str(item.get("id") or "") in allowed_ids
            ]
            results: list[dict[str, Any]] = []
            visible_ids = {str(item.get("id") or "") for item in libraries}
            for library in libraries:
                library_id = library.get("id")
                if not library_id:
                    continue
                for item in await abs_client.search_library(
                    str(library_id),
                    q.strip(),
                    limit=safe_limit,
                ):
                    if allowed_ids is not None and str(item.get("libraryId") or "") not in visible_ids:
                        continue
                    results.append(_public_item(item))
                    if len(results) >= safe_limit:
                        break
                if len(results) >= safe_limit:
                    break
    except (httpx.HTTPError, TypeError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail="media library is temporarily unavailable") from exc

    return {"bound": True, "query": q, "items": results, "count": len(results)}
