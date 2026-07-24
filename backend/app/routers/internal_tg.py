import secrets
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from app.config import Settings
from app.db import get_session
from app.internal_auth import require_internal_bot
from app.models import Code, PortalUser, TelegramNotification, utcnow
from app.routers.auth import default_abs_permissions, ensure_user_can_login, get_abs_client_factory
from app.routers.library import (
    _allowed_library_ids,
    _public_item,
    _public_library,
    _public_progress,
)
from app.security import hash_password
from app.services.account_lifecycle import preview_renewal, renew_user
from app.services.codes import CodeValidationError, redeem_code, validate_code
from app.services.expiry import disable_upstream_if_expired
from app.services.password_reset import PasswordResetError, create_password_reset_token
from app.services.provisioning import compensate_orphan_abs_user
from app.services.referrals import settle_referral_reward
from app.services.settings import get_public_settings
from app.services.telegram_binding import (
    TelegramBindingError,
    activate_binding_operation,
    bind_telegram_user,
    get_binding_operation,
    get_user_by_telegram_id,
    serialize_binding_operation,
)
from app.services.telegram_flows import (
    clear_flow,
    complete_flow,
    flow_payload,
    flow_state,
    get_flow,
    public_flow,
    save_flow,
)
from app.services.telegram_notifications import acknowledge_notification, claim_notifications
from app.services.usernames import archive_deleted_username, find_username_owner

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
    operationId: str | None = Field(default=None, min_length=8, max_length=128)


class TelegramIdRequest(BaseModel):
    telegramId: str = Field(min_length=1, max_length=64)
    telegramUsername: str | None = Field(default=None, max_length=128)


class RegisterRequest(BaseModel):
    telegramId: str = Field(min_length=1, max_length=64)
    telegramUsername: str | None = Field(default=None, max_length=128)
    username: str = Field(min_length=3, max_length=18, pattern=r"^[a-zA-Z0-9_.-]+$")
    inviteCode: str = Field(min_length=3, max_length=128)


class InviteCheckRequest(BaseModel):
    telegramId: str = Field(min_length=1, max_length=64)
    inviteCode: str = Field(min_length=3, max_length=128)


class UsernameCheckRequest(BaseModel):
    telegramId: str = Field(min_length=1, max_length=64)
    username: str = Field(min_length=3, max_length=18, pattern=r"^[a-zA-Z0-9_.-]+$")
    inviteCode: str | None = Field(default=None, min_length=3, max_length=128)


class FlowStartRequest(BaseModel):
    telegramId: str = Field(min_length=1, max_length=64)
    kind: Literal["register", "bind", "renew", "input"]
    step: str = Field(min_length=1, max_length=64)


class RenewPreviewRequest(BaseModel):
    telegramId: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=3, max_length=128)


class NotificationClaimRequest(BaseModel):
    limit: int = Field(default=10, ge=1, le=50)


class NotificationAckRequest(BaseModel):
    success: bool
    retryable: bool = True
    error: str | None = Field(default=None, max_length=1000)
    retryAfterSeconds: int | None = Field(default=None, ge=1, le=86400)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _server_url(session: Session) -> str:
    public_settings = get_public_settings(session)
    client = public_settings.get("client")
    configured = client.get("serverUrl") if isinstance(client, dict) else None
    return str(configured or Settings().portal_public_url).rstrip("/")


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


def _bound_response(
    user: PortalUser,
    session: Session,
    *,
    binding_operation: Any | None = None,
) -> dict[str, Any]:
    public_settings = get_public_settings(session)
    response = {
        "bound": True,
        "user": _internal_user(user),
        "serverUrl": _server_url(session),
        "features": public_settings.get("telegram", {}),
    }
    if binding_operation is not None:
        response["bindingOperation"] = serialize_binding_operation(binding_operation)
    return response


def _bound_user_or_404(session: Session, telegram_id: str) -> PortalUser:
    user = get_user_by_telegram_id(session, telegram_id)
    if user is None:
        raise HTTPException(status_code=404, detail="telegram account is not bound")
    return user


def _telegram_features(session: Session) -> dict[str, Any]:
    value = get_public_settings(session).get("telegram")
    return value if isinstance(value, dict) else {}


def _require_feature(session: Session, key: str) -> None:
    if _telegram_features(session).get(key, True) is False:
        raise HTTPException(status_code=403, detail="telegram feature is disabled")


def _new_initial_password() -> str:
    return secrets.token_urlsafe(12)


def _ensure_public_registration_allowed(session: Session, telegram_id: str) -> None:
    public_settings = get_public_settings(session)
    if public_settings.get("features", {}).get("registration", True) is False:
        raise HTTPException(status_code=403, detail="registration is currently disabled")
    if get_user_by_telegram_id(session, telegram_id.strip()) is not None:
        raise HTTPException(status_code=409, detail="telegram account already bound")


def _existing_username(session: Session, username: str) -> PortalUser | None:
    return find_username_owner(session, username)


@router.post("/flow/start")
def start_flow(payload: FlowStartRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    flow = save_flow(
        session,
        telegram_id=payload.telegramId,
        kind=payload.kind,
        step=payload.step,
    )
    return public_flow(flow)


@router.get("/flow/{telegram_id}")
def current_flow(telegram_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    flow, phase = flow_state(session, telegram_id)
    return public_flow(flow, phase=phase)


@router.delete("/flow/{telegram_id}")
def cancel_flow(telegram_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    return {"ok": True, "cleared": clear_flow(session, telegram_id)}


@router.post("/register/invite/check")
def check_register_invite(payload: InviteCheckRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    _ensure_public_registration_allowed(session, payload.telegramId)
    try:
        code = validate_code(session, payload.inviteCode, action="register")
    except CodeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    flow = save_flow(
        session,
        telegram_id=payload.telegramId,
        kind="register",
        step="register_username",
        payload={"codeId": code.id},
    )
    return {
        "ok": True,
        "flowId": flow.id,
        "durationDays": code.duration_days,
        "remainingUses": max(0, code.max_uses - code.used_count),
        "designatedUsername": code.designated_username,
    }


@router.post("/register/username/check")
def check_register_username(payload: UsernameCheckRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    _ensure_public_registration_allowed(session, payload.telegramId)
    flow = get_flow(session, payload.telegramId, kind="register")
    stored = flow_payload(flow) if flow else {}
    code = session.get(Code, str(stored.get("codeId") or "")) if flow else None
    try:
        if code is None and payload.inviteCode:
            code = validate_code(
                session,
                payload.inviteCode,
                username=payload.username,
                action="register",
            )
        elif code is not None:
            code = validate_code(
                session,
                code.code,
                username=payload.username,
                action="register",
            )
        else:
            raise CodeValidationError("registration flow expired")
    except CodeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    existing = _existing_username(session, payload.username)
    if existing is not None and existing.status != "deleted":
        raise HTTPException(status_code=409, detail="username already exists")
    flow = save_flow(
        session,
        telegram_id=payload.telegramId,
        kind="register",
        step="register_confirm",
        payload={"codeId": code.id, "username": payload.username},
    )
    return {
        "ok": True,
        "flowId": flow.id,
        "username": payload.username,
        "durationDays": code.duration_days,
    }


async def _register_account(
    *,
    telegram_id: str,
    telegram_username: str | None,
    username: str,
    invite_code: str,
    session: Session,
    abs_factory: Any,
) -> dict[str, Any]:
    telegram_id = telegram_id.strip()
    _ensure_public_registration_allowed(session, telegram_id)

    existing = _existing_username(session, username)
    if existing is not None and existing.status != "deleted":
        raise HTTPException(status_code=409, detail="username already exists")

    password = _new_initial_password()
    try:
        code = redeem_code(
            session,
            invite_code,
            username=username,
            action="register",
            commit=False,
        )
    except CodeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        async with abs_factory() as abs_client:
            abs_user = await abs_client.create_user(
                username=username,
                password=password,
                permissions=default_abs_permissions(),
                is_active=True,
            )
    except (httpx.HTTPError, TypeError, RuntimeError, KeyError) as exc:
        session.rollback()
        raise HTTPException(status_code=502, detail="upstream media server user creation failed") from exc

    expires_at = None if code.duration_days == 0 else utcnow() + timedelta(days=code.duration_days)
    try:
        if existing is not None:
            archive_deleted_username(session, existing)
        user = PortalUser(
            username=username,
            password_hash=hash_password(password),
            abs_user_id=abs_user["id"],
            abs_username=abs_user.get("username", username),
            expires_at=expires_at,
        )
        user.telegram_id = telegram_id
        user.telegram_username = (telegram_username or "").strip() or None
        user.telegram_bound_at = utcnow()
        user.telegram_binding_required = True
        user.updated_at = utcnow()
        session.add(user)
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        await compensate_orphan_abs_user(
            session,
            abs_factory=abs_factory,
            abs_user_id=str(abs_user["id"]),
            username=username,
            source="telegram_registration_commit_failure",
        )
        raise HTTPException(status_code=409, detail="username or telegram account already exists") from exc
    session.refresh(user)
    try:
        settle_referral_reward(session, code=code, registered_user=user)
    except Exception:  # noqa: BLE001 - registration succeeded; worker can settle later
        logger.exception("Failed to settle referral reward after Telegram registration")
    return {
        "created": True,
        "oneTimePassword": password,
        **_bound_response(user, session),
    }


@router.post("/register")
async def register(
    payload: RegisterRequest,
    session: Session = Depends(get_session),
    abs_factory: Any = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    return await _register_account(
        telegram_id=payload.telegramId,
        telegram_username=payload.telegramUsername,
        username=payload.username,
        invite_code=payload.inviteCode,
        session=session,
        abs_factory=abs_factory,
    )


@router.post("/register/confirm")
async def confirm_register(
    payload: TelegramIdRequest,
    session: Session = Depends(get_session),
    abs_factory: Any = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    flow = get_flow(session, payload.telegramId, kind="register")
    stored = flow_payload(flow) if flow else {}
    code = session.get(Code, str(stored.get("codeId") or "")) if flow else None
    username = str(stored.get("username") or "")
    if flow is None or flow.step != "register_confirm" or code is None or not username:
        raise HTTPException(status_code=409, detail="registration flow expired")
    result = await _register_account(
        telegram_id=payload.telegramId,
        telegram_username=payload.telegramUsername,
        username=username,
        invite_code=code.code,
        session=session,
        abs_factory=abs_factory,
    )
    complete_flow(session, payload.telegramId)
    return result


@router.post("/bind")
async def bind(
    payload: BindRequest,
    session: Session = Depends(get_session),
    abs_factory: Any = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    try:
        user = bind_telegram_user(
            session,
            code=payload.code,
            telegram_id=payload.telegramId,
            telegram_username=payload.telegramUsername,
            settings=Settings(),
            operation_id=payload.operationId,
        )
    except TelegramBindingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    operation = get_binding_operation(session, user)
    if operation is None:
        raise HTTPException(status_code=500, detail="binding operation was not created")
    operation = await activate_binding_operation(
        session,
        user,
        operation=operation,
        abs_factory=abs_factory,
    )
    session.refresh(user)
    complete_flow(session, payload.telegramId)
    return _bound_response(user, session, binding_operation=operation)


@router.get("/me/{telegram_id}")
async def me(
    telegram_id: str,
    session: Session = Depends(get_session),
    abs_factory: Any = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    user = get_user_by_telegram_id(session, telegram_id)
    if user is None:
        public_settings = get_public_settings(session)
        return {"bound": False, "features": public_settings.get("telegram", {})}
    operation = get_binding_operation(session, user)
    if operation is not None and operation.phase != "completed":
        operation = await activate_binding_operation(
            session,
            user,
            operation=operation,
            abs_factory=abs_factory,
        )
        session.refresh(user)
    await disable_upstream_if_expired(user, session, abs_factory)
    session.refresh(user)
    return _bound_response(user, session, binding_operation=operation)


@router.post("/open")
def open_account(payload: TelegramIdRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    user = _bound_user_or_404(session, payload.telegramId)
    ensure_user_can_login(user, session)
    if user.abs_user_id:
        return {"opened": True, "alreadyOpen": True, **_bound_response(user, session)}
    raise HTTPException(
        status_code=409,
        detail="portal account is missing an ABS account; please reset password in the web dashboard first",
    )


@router.get("/config")
def bot_config(session: Session = Depends(get_session)) -> dict[str, Any]:
    settings = get_public_settings(session)
    return {
        "siteName": settings.get("siteName"),
        "features": settings.get("telegram", {}),
        "announcement": settings.get("announcement", {}),
        "client": settings.get("client", {}),
        "links": settings.get("links", {}),
    }


@router.post("/renew/preview")
def renew_preview(
    payload: RenewPreviewRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_feature(session, "renewalEnabled")
    user = _bound_user_or_404(session, payload.telegramId)
    ensure_user_can_login(user, session)
    try:
        preview = preview_renewal(session, user, payload.code)
    except CodeValidationError as exc:
        status = 409 if str(exc) == "account already permanent" else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    flow = save_flow(
        session,
        telegram_id=payload.telegramId,
        kind="renew",
        step="renew_confirm",
        payload={"codeId": preview["codeId"]},
    )
    return {"ok": True, "flowId": flow.id, **preview}


@router.post("/renew/confirm")
async def renew_confirm(
    payload: TelegramIdRequest,
    session: Session = Depends(get_session),
    abs_factory: Any = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    _require_feature(session, "renewalEnabled")
    user = _bound_user_or_404(session, payload.telegramId)
    ensure_user_can_login(user, session)
    flow = get_flow(session, payload.telegramId, kind="renew")
    stored = flow_payload(flow) if flow else {}
    code = session.get(Code, str(stored.get("codeId") or "")) if flow else None
    if flow is None or flow.step != "renew_confirm" or code is None:
        raise HTTPException(status_code=409, detail="renewal flow expired")
    try:
        result = await renew_user(session, user, code, abs_factory=abs_factory)
    except CodeValidationError as exc:
        status = 409 if str(exc) == "account already permanent" else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    complete_flow(session, payload.telegramId)
    return {
        "ok": True,
        "redeemedCode": result["redeemedCode"],
        "upstreamReactivated": result["upstreamReactivated"],
        "message": result["message"],
        **_bound_response(result["user"], session),
    }


@router.post("/password-reset")
def password_reset_link(
    payload: TelegramIdRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _require_feature(session, "passwordResetEnabled")
    user = _bound_user_or_404(session, payload.telegramId)
    try:
        raw_token, token = create_password_reset_token(session, user)
    except PasswordResetError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    # Keep the one-time secret in the URL fragment. Fragments are not sent to
    # Nginx/API access logs or in the HTTP request target; the page scrubs it
    # from browser history immediately after reading it.
    url = Settings().portal_public_url.rstrip("/") + "/reset-password#token=" + raw_token
    return {"url": url, "expiresAt": token.expires_at.isoformat()}


@router.get("/recent/{telegram_id}")
async def recent_listening(
    telegram_id: str,
    limit: int = Query(default=5, ge=1, le=10),
    session: Session = Depends(get_session),
    abs_factory: Any = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    _require_feature(session, "recentListeningEnabled")
    user = _bound_user_or_404(session, telegram_id)
    ensure_user_can_login(user, session)
    try:
        async with abs_factory() as abs_client:
            upstream_user = await abs_client.get_user(user.abs_user_id) if user.abs_user_id else {}
            progress = upstream_user.get("mediaProgress", []) if isinstance(upstream_user, dict) else []
            allowed_ids = _allowed_library_ids(upstream_user if isinstance(upstream_user, dict) else {})
            recent = sorted(
                progress if isinstance(progress, list) else [],
                key=lambda item: item.get("lastUpdate") or 0,
                reverse=True,
            )
            visible_progress: list[dict[str, Any]] = []
            items_by_id: dict[str, dict[str, Any]] = {}
            for entry in recent:
                item_id = str(entry.get("libraryItemId") or "")
                if not item_id:
                    continue
                try:
                    item = await abs_client.get_library_item(item_id)
                except (httpx.HTTPError, TypeError, RuntimeError):
                    continue
                if allowed_ids is not None and str(item.get("libraryId") or "") not in allowed_ids:
                    continue
                visible_progress.append(entry)
                items_by_id[item_id] = item
                if len(visible_progress) >= limit:
                    break
    except (httpx.HTTPError, TypeError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail="media library is temporarily unavailable") from exc
    return {
        "bound": True,
        "progress": [_public_progress(item, items_by_id) for item in visible_progress],
        "count": len(visible_progress),
    }


@router.post("/notifications/claim")
def claim_notification_batch(
    payload: NotificationClaimRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    items = claim_notifications(session, limit=payload.limit)
    return {
        "items": [
            {
                "id": item.id,
                "telegramId": item.telegram_id,
                "kind": item.kind,
                "message": item.message,
                "dedupeKey": item.dedupe_key,
                "attempts": item.attempts,
            }
            for item in items
        ]
    }


@router.post("/notifications/{notification_id}/ack")
def ack_notification(
    notification_id: str,
    payload: NotificationAckRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    notification = session.get(TelegramNotification, notification_id)
    if notification is None:
        raise HTTPException(status_code=404, detail="notification not found")
    if notification.status == "sent":
        return {"ok": True, "status": notification.status}
    notification = acknowledge_notification(
        session,
        notification,
        success=payload.success,
        error=payload.error,
        retry_after_seconds=payload.retryAfterSeconds,
        retryable=payload.retryable,
    )
    return {"ok": True, "status": notification.status}


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
