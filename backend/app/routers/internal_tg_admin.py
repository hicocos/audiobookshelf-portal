import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from app.db import get_session
from app.internal_auth import require_internal_bot
from app.models import (
    AuditLog,
    MediaRequest,
    PortalUser,
    TelegramGroupMembership,
    TelegramNotification,
    utcnow,
)
from app.routers.auth import get_abs_client_factory
from app.services.telegram_admin import require_telegram_admin
from app.services.telegram_flows import (
    clear_flow,
    flow_payload,
    get_flow,
    save_flow,
    transition_flow_step,
)
from app.services.telegram_notifications import enqueue_notification
from app.services.media_requests import MediaRequestLimitError, transition_open_media_request
from app.services.reconciliation import (
    enqueue_reconciliation_job,
    process_reconciliation_jobs,
)
from app.worker_health import worker_health_status

router = APIRouter(
    prefix="/api/internal/tg/admin",
    tags=["internal-tg-admin"],
    dependencies=[Depends(require_internal_bot)],
)


class AdminTelegramRequest(BaseModel):
    telegramId: str = Field(min_length=1, max_length=64)


class AdminUserSearch(AdminTelegramRequest):
    query: str = Field(min_length=1, max_length=100)


class AdminUserList(AdminTelegramRequest):
    category: Literal["active", "expiring", "expired", "disabled"]
    limit: int = Field(default=10, ge=1, le=20)


class AdminActionPreview(AdminTelegramRequest):
    action: Literal["enable", "disable", "extend"]
    targetUserId: str = Field(min_length=1, max_length=64)
    extendDays: int | None = Field(default=None, ge=1, le=3650)


class AdminRequestUpdate(AdminTelegramRequest):
    status: Literal["accepted", "available", "rejected"]
    note: str | None = Field(default=None, max_length=500)


class AdminRequestReply(AdminTelegramRequest):
    message: str = Field(min_length=1, max_length=500)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _admin(session: Session, telegram_id: str) -> PortalUser:
    return require_telegram_admin(session, telegram_id)


def _user_data(user: PortalUser) -> dict[str, Any]:
    expiry = _aware(user.expires_at)
    return {
        "id": user.id,
        "username": user.username,
        "status": user.status,
        "expiresAt": expiry.isoformat() if expiry else None,
        "telegramId": user.telegram_id,
        "absUsername": user.abs_username,
    }


@router.post("/stats")
def admin_stats(
    payload: AdminTelegramRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    admin = _admin(session, payload.telegramId)
    counts = {
        status: session.exec(
            select(func.count(PortalUser.id)).where(
                PortalUser.role.notin_(["admin", "root"]),
                PortalUser.status == status,
            )
        ).one()
        for status in ("active", "expired", "disabled")
    }
    pending_requests = session.exec(
        select(func.count(MediaRequest.id)).where(MediaRequest.status == "pending")
    ).one()
    pending_notifications = session.exec(
        select(func.count(TelegramNotification.id)).where(
            TelegramNotification.status.in_(["pending", "retry", "sending"])
        )
    ).one()
    group_grace = session.exec(
        select(func.count(TelegramGroupMembership.id)).where(
            TelegramGroupMembership.status == "grace"
        )
    ).one()
    return {
        "admin": {"username": admin.username, "role": admin.role},
        "users": counts,
        "pendingRequests": pending_requests,
        "pendingNotifications": pending_notifications,
        "groupGrace": group_grace,
        "worker": worker_health_status(),
    }


@router.post("/users/search")
def search_users(
    payload: AdminUserSearch,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _admin(session, payload.telegramId)
    query = payload.query.strip().casefold()
    users = session.exec(
        select(PortalUser)
        .where(
            PortalUser.role.notin_(["admin", "root"]),
            PortalUser.status != "deleted",
        )
        .order_by(PortalUser.created_at.desc())
    ).all()
    matches = [user for user in users if query in user.username.casefold()][:10]
    return {"users": [_user_data(user) for user in matches]}


@router.post("/users/list")
def list_users(
    payload: AdminUserList,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _admin(session, payload.telegramId)
    statement = select(PortalUser).where(
        PortalUser.role.notin_(["admin", "root"]),
        PortalUser.status != "deleted",
    )
    if payload.category == "expiring":
        now = utcnow()
        statement = statement.where(
            PortalUser.status == "active",
            PortalUser.expires_at.is_not(None),
            PortalUser.expires_at > now,
            PortalUser.expires_at <= now + timedelta(days=7),
        ).order_by(PortalUser.expires_at)
    else:
        statement = statement.where(PortalUser.status == payload.category).order_by(
            PortalUser.updated_at.desc()
        )
    users = session.exec(statement.limit(payload.limit)).all()
    return {
        "category": payload.category,
        "users": [_user_data(user) for user in users],
    }


@router.post("/actions/preview")
def preview_admin_action(
    payload: AdminActionPreview,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    admin = _admin(session, payload.telegramId)
    target = session.get(PortalUser, payload.targetUserId)
    if target is None or target.role in {"admin", "root"} or target.status == "deleted":
        raise HTTPException(status_code=404, detail="user not found")
    if payload.action == "extend" and payload.extendDays is None:
        raise HTTPException(status_code=422, detail="extend days required")
    if payload.action == "enable":
        expiry = _aware(target.expires_at)
        if expiry is not None and expiry <= utcnow():
            raise HTTPException(status_code=409, detail="extend expired user before enabling")
    flow = save_flow(
        session,
        telegram_id=payload.telegramId,
        kind="admin",
        step="admin_action_confirm",
        payload={
            "adminUserId": admin.id,
            "action": payload.action,
            "targetUserId": target.id,
            "extendDays": payload.extendDays,
        },
    )
    return {
        "flowId": flow.id,
        "action": payload.action,
        "target": _user_data(target),
        "extendDays": payload.extendDays,
    }


@router.post("/actions/confirm")
async def confirm_admin_action(
    payload: AdminTelegramRequest,
    session: Session = Depends(get_session),
    abs_factory: Any = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    admin = _admin(session, payload.telegramId)
    flow = get_flow(session, payload.telegramId, kind="admin")
    stored = flow_payload(flow) if flow else {}
    if (
        flow is None
        or flow.step != "admin_action_confirm"
        or stored.get("adminUserId") != admin.id
    ):
        raise HTTPException(status_code=409, detail="admin confirmation expired")
    target = session.get(PortalUser, str(stored.get("targetUserId") or ""))
    if target is None or target.role in {"admin", "root"}:
        raise HTTPException(status_code=404, detail="user not found")
    action = str(stored.get("action") or "")
    if action not in {"enable", "disable", "extend"}:
        raise HTTPException(status_code=409, detail="unsupported admin action")
    days = int(stored.get("extendDays") or 0)
    current = _aware(target.expires_at)
    if action == "extend" and days < 1:
        raise HTTPException(status_code=422, detail="extend days required")
    if action == "extend" and current is None:
        raise HTTPException(status_code=409, detail="permanent account needs no extension")
    if action == "enable" and current is not None and current <= utcnow():
        raise HTTPException(status_code=409, detail="extend expired user before enabling")
    if not transition_flow_step(
        session,
        flow_id=flow.id,
        expected_step="admin_action_confirm",
        next_step="admin_action_processing",
    ):
        raise HTTPException(status_code=409, detail="admin action already processing")

    detail: dict[str, Any] = {"action": action}
    desired_upstream_active: bool | None = None
    if action in {"enable", "disable"}:
        is_active = action == "enable"
        desired_upstream_active = is_active
        target.status = "active" if is_active else "disabled"
        if not is_active:
            target.session_version = int(target.session_version or 0) + 1
    elif action == "extend":
        now = utcnow()
        target.expires_at = (current if current > now else now) + timedelta(days=days)
        detail["extendDays"] = days
        if target.status == "expired":
            desired_upstream_active = True
            target.status = "active"
    target.updated_at = utcnow()
    session.add(target)
    session.add(
        AuditLog(
            actor_user_id=admin.id,
            actor_username=admin.username,
            action=f"telegram.admin.user.{action}",
            target_type="portal_user",
            target_id=target.id,
            detail_json=json.dumps(detail, ensure_ascii=False),
        )
    )
    job = None
    if target.abs_user_id and desired_upstream_active is not None:
        job = enqueue_reconciliation_job(
            session,
            idempotency_key=f"telegram-admin:{flow.id}",
            operation="set_active",
            target_type="portal_user",
            target_id=target.id,
            abs_user_id=target.abs_user_id,
            payload={
                "isActive": desired_upstream_active,
                "source": "telegram_admin",
            },
        )
    try:
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        transition_flow_step(
            session,
            flow_id=flow.id,
            expected_step="admin_action_processing",
            next_step="admin_action_confirm",
        )
        raise HTTPException(status_code=503, detail="admin action was not committed") from exc
    upstream_synced = True
    if job is not None:
        async with abs_factory() as abs_client:
            await process_reconciliation_jobs(session, abs_client, limit=1, job_id=job.id)
        session.refresh(job)
        upstream_synced = job.status == "succeeded"
    clear_flow(session, payload.telegramId)
    session.refresh(target)
    return {
        "ok": True,
        "user": _user_data(target),
        "upstreamSynced": upstream_synced,
        "reconciliationJobId": job.id if job and not upstream_synced else None,
    }


@router.post("/requests/list")
def list_admin_requests(
    payload: AdminTelegramRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _admin(session, payload.telegramId)
    items = session.exec(
        select(MediaRequest)
        .where(MediaRequest.status.in_(["pending", "accepted"]))
        .order_by(MediaRequest.created_at)
        .limit(30)
    ).all()
    return {
        "items": [
            {
                "id": item.id,
                "kind": item.kind,
                "title": item.title,
                "details": item.details,
                "status": item.status,
                "createdAt": item.created_at.isoformat(),
                "username": (
                    session.get(PortalUser, item.portal_user_id).username
                    if session.get(PortalUser, item.portal_user_id)
                    else "unknown"
                ),
            }
            for item in items
        ]
    }


@router.post("/requests/{request_id}")
def update_admin_request(
    request_id: str,
    payload: AdminRequestUpdate,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    admin = _admin(session, payload.telegramId)
    item = session.get(MediaRequest, request_id)
    if item is None:
        raise HTTPException(status_code=404, detail="media request not found")
    try:
        item = transition_open_media_request(
            session,
            request_id=item.id,
            status=payload.status,
            admin_note=(payload.note or "").strip() or None,
            handled_by_user_id=admin.id,
        )
    except MediaRequestLimitError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.add(
        AuditLog(
            actor_user_id=admin.id,
            actor_username=admin.username,
            action=f"telegram.admin.media_request.{payload.status}",
            target_type="media_request",
            target_id=item.id,
        )
    )
    session.commit()
    requester = session.get(PortalUser, item.portal_user_id)
    if requester and requester.telegram_id:
        enqueue_notification(
            session,
            dedupe_key=f"media-request-status:{item.id}:{payload.status}",
            telegram_id=requester.telegram_id,
            kind="media_request_status",
            message=(
                "您的工单已受理，请等待管理员处理。详细信息请到 Web 端查看。"
                if payload.status == "accepted"
                else "您的工单已经处理。详细信息请到 Web 端查看。"
            ),
        )
    return {"ok": True, "status": item.status}


@router.post("/requests/{request_id}/reply")
def reply_admin_request(
    request_id: str,
    payload: AdminRequestReply,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    admin = _admin(session, payload.telegramId)
    item = session.get(MediaRequest, request_id)
    if item is None:
        raise HTTPException(status_code=404, detail="media request not found")
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="reply cannot be blank")
    item.admin_note = message
    item.handled_by_user_id = admin.id
    item.updated_at = utcnow()
    session.add(item)
    session.add(
        AuditLog(
            actor_user_id=admin.id,
            actor_username=admin.username,
            action="telegram.admin.media_request.reply",
            target_type="media_request",
            target_id=item.id,
            detail_json=json.dumps({"messageLength": len(message)}),
        )
    )
    session.commit()
    requester = session.get(PortalUser, item.portal_user_id)
    if requester and requester.telegram_id:
        enqueue_notification(
            session,
            dedupe_key=f"media-request-reply:{item.id}:{item.updated_at.isoformat()}",
            telegram_id=requester.telegram_id,
            kind="media_request_reply",
            message=f"管理员回复《{item.title}》：\n{message}",
        )
    return {"ok": True, "message": message}
