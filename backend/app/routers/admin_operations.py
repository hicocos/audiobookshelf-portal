import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.auth_deps import require_admin
from app.db import get_session
from app.models import (
    AuditLog,
    MediaRequest,
    PointAccount,
    PortalUser,
    ReferralInvite,
    TelegramGroupMembership,
    TelegramNotification,
    utcnow,
)
from app.routers.auth import get_abs_client_factory
from app.services.inactivity import sync_inactive_users
from app.services.rewards import RewardError, credit_points, debit_points
from app.services.settings import get_public_settings
from app.services.media_requests import MediaRequestLimitError, media_request_status_label, transition_open_media_request
from app.services.notification_retry import NotificationRetryError, retry_notification_safely
from app.services.telegram_notifications import enqueue_notification
from app.worker_health import worker_health_status

router = APIRouter(prefix="/api/admin/operations", tags=["admin-operations"])


class RequestUpdate(BaseModel):
    status: Literal["accepted", "available", "rejected"]
    note: str | None = Field(default=None, max_length=500)


class NotificationRetryRequest(BaseModel):
    expectedVersion: int = Field(ge=0)


class PointAdjustment(BaseModel):
    userId: str = Field(min_length=1, max_length=64)
    amount: int = Field(ge=-1_000_000, le=1_000_000)
    note: str = Field(min_length=1, max_length=300)


BroadcastAudience = Literal["active", "expiring_7d", "expired", "all_bound"]


class BroadcastRequest(BaseModel):
    audience: BroadcastAudience
    message: str = Field(min_length=1, max_length=4000)
    confirmCount: int = Field(ge=1, le=100_000)
    idempotencyKey: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


def _broadcast_replay(session: Session, batch_id: str) -> dict[str, Any] | None:
    audit = session.exec(
        select(AuditLog).where(
            AuditLog.action == "admin.telegram_broadcast.enqueue",
            AuditLog.target_id == batch_id,
        )
    ).first()
    if audit is None:
        return None
    queued = session.exec(
        select(func.count()).select_from(TelegramNotification).where(
            TelegramNotification.dedupe_key.like(f"admin-broadcast:{batch_id}:%")
        )
    ).one()
    return {"ok": True, "batchId": batch_id, "queued": int(queued), "idempotentReplay": True}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _broadcast_recipients(
    session: Session, audience: BroadcastAudience
) -> list[PortalUser]:
    now = utcnow()
    seven_days = now + timedelta(days=7)
    users = session.exec(
        select(PortalUser).where(
            PortalUser.telegram_id.is_not(None),
            PortalUser.telegram_id != "",
            PortalUser.role.notin_(["admin", "root"]),
            PortalUser.status != "deleted",
        )
    ).all()

    def included(user: PortalUser) -> bool:
        expiry = _aware(user.expires_at)
        is_expired = user.status == "expired" or bool(expiry and expiry <= now)
        if audience == "all_bound":
            return True
        if audience == "expired":
            return is_expired
        if audience == "expiring_7d":
            return bool(
                user.status == "active" and expiry and now < expiry <= seven_days
            )
        return user.status == "active" and not is_expired

    return [user for user in users if included(user)]


def _serialize_request(session: Session, item: MediaRequest) -> dict[str, Any]:
    user = session.get(PortalUser, item.portal_user_id)
    return {
        "id": item.id,
        "username": user.username if user else "unknown",
        "kind": item.kind,
        "title": item.title,
        "details": item.details,
        "status": item.status,
        "statusLabel": media_request_status_label(item.status),
        "adminNote": item.admin_note,
        "createdAt": item.created_at.isoformat(),
        "updatedAt": item.updated_at.isoformat(),
    }


@router.get("/overview")
def overview(
    _claims: dict[str, Any] = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    user_counts = {
        status: session.exec(
            select(func.count(PortalUser.id)).where(
                PortalUser.role.notin_(["admin", "root"]),
                PortalUser.status == status,
            )
        ).one()
        for status in ("active", "expired", "disabled")
    }
    notification_counts = {
        status: session.exec(
            select(func.count(TelegramNotification.id)).where(
                TelegramNotification.status == status
            )
        ).one()
        for status in ("pending", "retry", "sending", "failed")
    }
    return {
        "users": user_counts,
        "pendingRequests": session.exec(
            select(func.count(MediaRequest.id)).where(
                MediaRequest.status.in_(["pending", "accepted"])
            )
        ).one(),
        "notifications": notification_counts,
        "groupGrace": session.exec(
            select(func.count(TelegramGroupMembership.id)).where(
                TelegramGroupMembership.status == "grace"
            )
        ).one(),
        "referrals": session.exec(select(func.count(ReferralInvite.id))).one(),
        "pointAccounts": session.exec(select(func.count(PointAccount.portal_user_id))).one(),
        "worker": worker_health_status(),
    }


@router.get("/requests")
def list_requests(
    status: Literal["pending", "accepted", "available", "rejected"] | None = None,
    limit: int = 100,
    offset: int = 0,
    _claims: dict[str, Any] = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    safe_limit, safe_offset = max(1, min(limit, 200)), max(0, offset)
    statement = select(MediaRequest)
    count_statement = select(func.count(MediaRequest.id))
    if status is not None:
        statement = statement.where(MediaRequest.status == status)
        count_statement = count_statement.where(MediaRequest.status == status)
    statement = statement.order_by(MediaRequest.created_at.desc(), MediaRequest.id.desc()).offset(safe_offset).limit(safe_limit)
    items = session.exec(statement).all()
    return {
        "items": [_serialize_request(session, item) for item in items],
        "total": int(session.exec(count_statement).one()),
        "limit": safe_limit,
        "offset": safe_offset,
    }


@router.post("/requests/{request_id}")
def update_request(
    request_id: str,
    payload: RequestUpdate,
    claims: dict[str, Any] = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    item = session.get(MediaRequest, request_id)
    if item is None:
        raise HTTPException(status_code=404, detail="未找到该工单。")
    try:
        item = transition_open_media_request(
            session,
            request_id=item.id,
            status=payload.status,
            admin_note=(payload.note or "").strip() or None,
            handled_by_user_id=str(claims.get("sub") or "") or None,
        )
    except MediaRequestLimitError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.add(
        AuditLog(
            actor_user_id=str(claims.get("sub") or "") or None,
            actor_username=str(claims.get("username") or "admin"),
            action=f"admin.media_request.{payload.status}",
            target_type="media_request",
            target_id=item.id,
            detail_json=json.dumps({"note": item.admin_note}, ensure_ascii=False),
        )
    )
    session.commit()
    requester = session.get(PortalUser, item.portal_user_id)
    status_label = media_request_status_label(payload.status)
    default_next = {
        "accepted": "管理员正在处理，请等待后续通知。",
        "available": "内容已上架，请打开 Web 工单详情或媒体客户端查看。",
        "rejected": "本次未采纳；如备注给出补充要求，可完善信息后重新提交。",
    }[payload.status]
    if requester and requester.telegram_id:
        note = item.admin_note or "管理员未填写备注。"
        enqueue_notification(
            session,
            dedupe_key=f"media-request-status:{item.id}:{payload.status}",
            telegram_id=requester.telegram_id,
            kind="media_request_status",
            message=(
                f"你的有声书工单《{item.title}》状态已更新：{status_label}。\n"
                f"管理员备注：{note}\n"
                f"下一步：{default_next}"
            ),
        )
    return {"item": _serialize_request(session, item)}


@router.get("/notifications")
def list_notifications(
    status: Literal["pending", "retry", "sending", "sent", "failed"] | None = None,
    limit: int = 100,
    offset: int = 0,
    _claims: dict[str, Any] = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    safe_limit, safe_offset = max(1, min(limit, 200)), max(0, offset)
    statement = select(TelegramNotification)
    count_statement = select(func.count(TelegramNotification.id))
    if status is not None:
        statement = statement.where(TelegramNotification.status == status)
        count_statement = count_statement.where(TelegramNotification.status == status)
    statement = statement.order_by(TelegramNotification.created_at.desc(), TelegramNotification.id.desc()).offset(safe_offset).limit(safe_limit)
    items = session.exec(statement).all()
    return {
        "total": int(session.exec(count_statement).one()),
        "limit": safe_limit,
        "offset": safe_offset,
        "items": [
            {
                "id": item.id,
                "telegramId": item.telegram_id,
                "kind": item.kind,
                "message": item.message,
                "status": item.status,
                "attempts": item.attempts,
                "version": item.version,
                "claimedAt": item.claimed_at.isoformat() if item.claimed_at else None,
                "lastError": item.last_error,
                "createdAt": item.created_at.isoformat(),
                "sentAt": item.sent_at.isoformat() if item.sent_at else None,
            }
            for item in items
        ]
    }


@router.post("/notifications/{notification_id}/retry")
def retry_notification(
    notification_id: str,
    payload: NotificationRetryRequest,
    claims: dict[str, Any] = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        item = retry_notification_safely(
            session,
            notification_id,
            actor=str(claims.get("username") or "admin"),
            expected_version=payload.expectedVersion,
        )
    except NotificationRetryError as exc:
        status = 404 if str(exc) == "notification not found" else 409
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return {"ok": True, "status": item.status, "version": item.version}


@router.get("/broadcast/preview")
def preview_broadcast(
    audience: BroadcastAudience = "active",
    _claims: dict[str, Any] = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    recipients = _broadcast_recipients(session, audience)
    return {
        "audience": audience,
        "count": len(recipients),
        "sample": [user.username for user in recipients[:10]],
    }


@router.post("/broadcast")
def create_broadcast(
    payload: BroadcastRequest,
    claims: dict[str, Any] = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    batch_id = payload.idempotencyKey
    replay = _broadcast_replay(session, batch_id)
    if replay is not None:
        return replay
    recipients = _broadcast_recipients(session, payload.audience)
    if len(recipients) != payload.confirmCount:
        raise HTTPException(
            status_code=409,
            detail="接收人数已变化，请重新预览后确认。",
        )
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="广播内容不能为空。")
    for user in recipients:
        session.add(
            TelegramNotification(
                dedupe_key=f"admin-broadcast:{batch_id}:{user.telegram_id}",
                telegram_id=str(user.telegram_id),
                kind="admin_broadcast",
                message=message,
            )
        )
    session.add(
        AuditLog(
            actor_user_id=str(claims.get("sub") or "") or None,
            actor_username=str(claims.get("username") or "admin"),
            action="admin.telegram_broadcast.enqueue",
            target_type="telegram_broadcast",
            target_id=batch_id,
            detail_json=json.dumps(
                {
                    "audience": payload.audience,
                    "count": len(recipients),
                    "messageLength": len(message),
                },
                ensure_ascii=False,
            ),
        )
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        replay = _broadcast_replay(session, batch_id)
        if replay is not None:
            return replay
        raise
    return {
        "ok": True,
        "batchId": batch_id,
        "queued": len(recipients),
        "idempotentReplay": False,
    }


@router.get("/memberships")
def list_memberships(
    status: Literal["member", "grace", "disabled"] | None = None,
    limit: int = 100,
    offset: int = 0,
    _claims: dict[str, Any] = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    safe_limit, safe_offset = max(1, min(limit, 200)), max(0, offset)
    statement = select(TelegramGroupMembership)
    count_statement = select(func.count(TelegramGroupMembership.id))
    if status is not None:
        statement = statement.where(TelegramGroupMembership.status == status)
        count_statement = count_statement.where(TelegramGroupMembership.status == status)
    statement = statement.order_by(TelegramGroupMembership.updated_at.desc(), TelegramGroupMembership.id.desc()).offset(safe_offset).limit(safe_limit)
    items = session.exec(statement).all()
    return {
        "total": int(session.exec(count_statement).one()),
        "limit": safe_limit,
        "offset": safe_offset,
        "items": [
            {
                "id": item.id,
                "username": (
                    session.get(PortalUser, item.portal_user_id).username
                    if session.get(PortalUser, item.portal_user_id)
                    else "unknown"
                ),
                "telegramId": item.telegram_id,
                "groupId": item.group_id,
                "status": item.status,
                "graceExpiresAt": (
                    item.grace_expires_at.isoformat() if item.grace_expires_at else None
                ),
                "lastCheckedAt": item.last_checked_at.isoformat(),
            }
            for item in items
        ]
    }


@router.get("/audit")
def list_audit(
    limit: int = 100,
    offset: int = 0,
    actor: str | None = None,
    action: str | None = None,
    targetType: str | None = None,
    _claims: dict[str, Any] = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    safe_limit, safe_offset = max(1, min(limit, 200)), max(0, offset)
    statement, count_statement = select(AuditLog), select(func.count(AuditLog.id))
    conditions = [
        AuditLog.actor_username == actor if actor else None,
        AuditLog.action == action if action else None,
        AuditLog.target_type == targetType if targetType else None,
    ]
    for condition in conditions:
        if condition is not None:
            statement, count_statement = statement.where(condition), count_statement.where(condition)
    items = session.exec(statement.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset(safe_offset).limit(safe_limit)).all()
    return {
        "total": int(session.exec(count_statement).one()),
        "limit": safe_limit,
        "offset": safe_offset,
        "items": [
            {
                "id": item.id,
                "actor": item.actor_username,
                "action": item.action,
                "targetType": item.target_type,
                "targetId": item.target_id,
                "detail": json.loads(item.detail_json) if item.detail_json else None,
                "createdAt": item.created_at.isoformat(),
            }
            for item in items
        ]
    }


@router.post("/points/adjust")
def adjust_points(
    payload: PointAdjustment,
    claims: dict[str, Any] = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    if payload.amount == 0:
        raise HTTPException(status_code=422, detail="积分调整不能为 0。")
    user = session.get(PortalUser, payload.userId)
    if user is None or user.role in {"admin", "root"}:
        raise HTTPException(status_code=404, detail="未找到该用户。")
    reference = f"admin-adjust:{uuid4()}"
    try:
        entry = (
            credit_points(
                session,
                user,
                amount=payload.amount,
                kind="admin_adjustment",
                reference=reference,
                detail={"note": payload.note},
            )
            if payload.amount > 0
            else debit_points(
                session,
                user,
                amount=-payload.amount,
                kind="admin_adjustment",
                reference=reference,
                detail={"note": payload.note},
            )
        )
    except RewardError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.add(
        AuditLog(
            actor_user_id=str(claims.get("sub") or "") or None,
            actor_username=str(claims.get("username") or "admin"),
            action="admin.points.adjust",
            target_type="portal_user",
            target_id=user.id,
            detail_json=json.dumps(
                {"amount": payload.amount, "note": payload.note}, ensure_ascii=False
            ),
        )
    )
    session.commit()
    return {"ok": True, "balance": entry.balance_after}


@router.post("/inactivity/preview")
async def preview_inactivity(
    _claims: dict[str, Any] = Depends(require_admin),
    session: Session = Depends(get_session),
    abs_factory: Any = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    settings = get_public_settings(session)
    operations = settings.get("operations")
    operations = operations if isinstance(operations, dict) else {}
    async with abs_factory() as abs_client:
        return await sync_inactive_users(
            session,
            abs_client,
            enabled=True,
            inactive_days=int(operations.get("inactiveDays") or 30),
            new_user_grace_days=int(operations.get("newUserGraceDays") or 7),
            actor="admin-preview",
            dry_run=True,
        )
