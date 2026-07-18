"""Admin user management endpoints.

Brings core Audiobookshelf user administration into the portal so the ABS
backend no longer needs to be opened directly: list / create / set password /
enable / disable / delete / adjust expiry. Every mutation writes an AuditLog
row and keeps the portal DB and the upstream ABS account in sync.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from app.abs_client import AudiobookshelfClient
from app.auth_deps import require_admin
from app.config import Settings
from app.db import get_session
from app.models import AuditLog, PortalUser, ReconciliationJob, utcnow
from app.routers.auth import default_abs_permissions, get_abs_client_factory
from app.security import hash_password
from app.services.reconciliation import (
    enqueue_reconciliation_job,
    process_reconciliation_jobs,
)

router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=256)
    durationDays: int = Field(default=30, ge=0, le=3650)
    email: str | None = None
    note: str | None = None


class SetPasswordRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class SetStatusRequest(BaseModel):
    action: Literal["enable", "disable"]


class SetExpiryRequest(BaseModel):
    # Mutually-exclusive intents handled in priority order below.
    expiresAt: datetime | None = None          # set absolute expiry
    extendDays: int | None = Field(default=None, ge=-3650, le=3650)  # relative shift
    clear: bool = False                        #永久 (no expiry)


class BulkExpiryRequest(BaseModel):
    extendDays: int = Field(ge=1, le=3650)
    reason: str | None = Field(default=None, max_length=200)


class BulkExpiryPreviewRequest(BaseModel):
    extendDays: int = Field(ge=1, le=3650)


class RetryReconciliationRequest(BaseModel):
    force: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _serialize(user: PortalUser, upstream: dict[str, Any] | None) -> dict[str, Any]:
    expires_at = _aware(user.expires_at)
    now = utcnow()
    is_expired = bool(expires_at and expires_at <= now)
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "status": user.status,
        "absUserId": user.abs_user_id,
        "absUsername": user.abs_username,
        "expiresAt": expires_at.isoformat() if expires_at else None,
        "isExpired": is_expired,
        "createdAt": user.created_at.isoformat() if user.created_at else None,
        "lastLoginAt": user.last_login_at.isoformat() if user.last_login_at else None,
        "upstreamActive": (upstream or {}).get("isActive") if upstream else None,
        "upstreamFound": upstream is not None,
    }


def _audit(
    session: Session,
    claims: dict[str, Any],
    action: str,
    target: PortalUser,
    detail: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_user_id=str(claims.get("sub") or ""),
            actor_username=str(claims.get("username") or "admin"),
            action=action,
            target_type="portal_user",
            target_id=target.id,
            detail_json=json.dumps(detail, ensure_ascii=False) if detail else None,
        )
    )




def _active_admin_count(session: Session) -> int:
    return session.exec(
        select(func.count(PortalUser.id)).where(
            PortalUser.status == "active",
            PortalUser.role.in_(["admin", "root"]),
        )
    ).one()


def _ensure_admin_can_disable_or_delete(
    session: Session,
    *,
    actor_id: str | None,
    target: PortalUser,
) -> None:
    if actor_id and target.id == actor_id:
        raise HTTPException(status_code=400, detail="不能禁用或删除当前登录的管理员账号。")
    if target.role in {"admin", "root"} and target.status == "active" and _active_admin_count(session) <= 1:
        raise HTTPException(status_code=400, detail="不能禁用或删除最后一个管理员账号。")

def _min_password_length() -> int:
    return max(1, int(Settings().portal_password_min_length))


def _abs_error() -> HTTPException:
    return HTTPException(status_code=502, detail="媒体服务器暂时不可用，操作未完成，请稍后重试。")


async def _process_reconciliation_now(
    session: Session,
    abs_factory: Callable[[], AudiobookshelfClient],
    job: ReconciliationJob,
) -> bool:
    try:
        async with abs_factory() as abs_client:
            await process_reconciliation_jobs(
                session,
                abs_client,
                limit=1,
                job_id=job.id,
            )
    except Exception:  # noqa: BLE001 - the durable job remains retryable
        return False
    session.refresh(job)
    return job.status == "succeeded"


def _bulk_expiry_candidates(session: Session) -> tuple[list[PortalUser], list[PortalUser]]:
    users = session.exec(
        select(PortalUser)
        .where(
            PortalUser.status != "deleted",
            PortalUser.role.notin_(["admin", "root"]),
        )
        .order_by(PortalUser.created_at.desc())
    ).all()
    skipped_admins = session.exec(
        select(PortalUser).where(
            PortalUser.status != "deleted",
            PortalUser.role.in_(["admin", "root"]),
        )
    ).all()
    return users, skipped_admins


def _bulk_expiry_preview_summary(
    users: list[PortalUser],
    skipped_admins: list[PortalUser],
    extend_days: int,
) -> dict[str, int]:
    now = utcnow()
    active = 0
    expired = 0
    disabled = 0
    permanent = 0
    reactivatable = 0
    for user in users:
        expires_at = _aware(user.expires_at)
        if user.status == "disabled":
            disabled += 1
        if expires_at is None:
            permanent += 1
            continue
        if user.status == "expired" or expires_at <= now:
            expired += 1
            next_expiry = now + timedelta(days=extend_days)
            if user.status == "expired" and next_expiry > now:
                reactivatable += 1
        elif user.status == "active":
            active += 1
    return {
        "matched": len(users),
        "affected": len(users) - permanent,
        "active": active,
        "expired": expired,
        "disabled": disabled,
        "permanent": permanent,
        "reactivatable": reactivatable,
        "skippedAdmins": len(skipped_admins),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/reconciliation")
def list_reconciliation_jobs(
    status: Literal["pending", "retry", "failed", "succeeded"] | None = None,
    _claims: dict[str, Any] = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    statement = select(ReconciliationJob).order_by(ReconciliationJob.created_at.desc()).limit(200)
    if status is not None:
        statement = statement.where(ReconciliationJob.status == status)
    jobs = session.exec(statement).all()
    return {
        "jobs": [
            {
                "id": job.id,
                "operation": job.operation,
                "targetType": job.target_type,
                "targetId": job.target_id,
                "status": job.status,
                "attempts": job.attempts,
                "nextRetryAt": job.next_retry_at.isoformat(),
                "lastError": job.last_error,
                "createdAt": job.created_at.isoformat(),
                "updatedAt": job.updated_at.isoformat(),
            }
            for job in jobs
        ]
    }


@router.post("/reconciliation/{job_id}/retry")
def retry_reconciliation_job(
    job_id: str,
    _payload: RetryReconciliationRequest,
    _claims: dict[str, Any] = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    job = session.get(ReconciliationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="未找到该对账任务。")
    if job.status == "succeeded":
        raise HTTPException(status_code=409, detail="该对账任务已成功，无需重试。")
    job.status = "retry"
    job.next_retry_at = utcnow()
    job.last_error = None
    job.updated_at = utcnow()
    session.add(job)
    session.commit()
    return {"ok": True, "id": job.id, "status": job.status}


@router.get("")
async def list_users(
    _claims: dict[str, Any] = Depends(require_admin),
    session: Session = Depends(get_session),
    abs_factory: Callable[[], AudiobookshelfClient] = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    portal_users = session.exec(
        select(PortalUser)
        .where(
            PortalUser.status != "deleted",
            PortalUser.role.notin_(["admin", "root"]),
        )
        .order_by(PortalUser.created_at.desc())
    ).all()

    upstream_by_id: dict[str, dict[str, Any]] = {}
    upstream_available = True
    try:
        async with abs_factory() as abs_client:
            for item in await abs_client.list_users():
                if item.get("id"):
                    upstream_by_id[str(item["id"])] = item
    except (httpx.HTTPError, TypeError, RuntimeError):
        upstream_available = False

    users = [
        _serialize(user, upstream_by_id.get(str(user.abs_user_id)) if user.abs_user_id else None)
        for user in portal_users
    ]
    return {
        "users": users,
        "stats": {
            "total": len(users),
            "active": sum(1 for u in users if u["status"] == "active"),
            "disabled": sum(1 for u in users if u["status"] == "disabled"),
            "expired": sum(1 for u in users if u["isExpired"]),
        },
        "upstreamAvailable": upstream_available,
    }


@router.post("")
async def create_user(
    payload: CreateUserRequest,
    claims: dict[str, Any] = Depends(require_admin),
    session: Session = Depends(get_session),
    abs_factory: Callable[[], AudiobookshelfClient] = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    if len(payload.password) < _min_password_length():
        raise HTTPException(status_code=422, detail=f"密码至少需要 {_min_password_length()} 位字符。")

    existing = session.exec(
        select(PortalUser).where(func.lower(PortalUser.username) == payload.username.lower())
    ).first()
    if existing and existing.status != "deleted":
        raise HTTPException(status_code=409, detail="该用户名已存在。")

    try:
        async with abs_factory() as abs_client:
            abs_user = await abs_client.create_user(
                username=payload.username,
                password=payload.password,
                permissions=default_abs_permissions(),
                is_active=True,
            )
    except (httpx.HTTPError, TypeError, RuntimeError, KeyError) as exc:
        raise _abs_error() from exc

    expires_at = None if payload.durationDays == 0 else utcnow() + timedelta(days=payload.durationDays)
    if existing is not None:
        # Revive a previously soft-deleted username on the same row.
        existing.password_hash = hash_password(payload.password)
        existing.email = payload.email
        existing.abs_user_id = abs_user["id"]
        existing.abs_username = abs_user.get("username", payload.username)
        existing.sync_normalized_usernames()
        existing.expires_at = expires_at
        existing.status = "active"
        existing.role = "user" if existing.role == "admin" else existing.role
        existing.updated_at = utcnow()
        user = existing
    else:
        user = PortalUser(
            username=payload.username,
            password_hash=hash_password(payload.password),
            email=payload.email,
            abs_user_id=abs_user["id"],
            abs_username=abs_user.get("username", payload.username),
            expires_at=expires_at,
        )
    session.add(user)
    _audit(session, claims, "admin.user.create", user, {"durationDays": payload.durationDays, "note": payload.note})
    try:
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        try:
            async with abs_factory() as abs_client:
                await abs_client.delete_user(str(abs_user["id"]))
        except (httpx.HTTPError, TypeError, RuntimeError, KeyError):
            pass
        raise HTTPException(status_code=409, detail="该用户名已存在。") from exc
    session.refresh(user)
    return {"user": _serialize(user, {"isActive": True})}


@router.post("/{user_id}/password")
async def set_password(
    user_id: str,
    payload: SetPasswordRequest,
    claims: dict[str, Any] = Depends(require_admin),
    session: Session = Depends(get_session),
    abs_factory: Callable[[], AudiobookshelfClient] = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    user = session.get(PortalUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="未找到该用户。")
    if len(payload.password) < _min_password_length():
        raise HTTPException(status_code=422, detail=f"密码至少需要 {_min_password_length()} 位字符。")

    if user.abs_user_id:
        try:
            async with abs_factory() as abs_client:
                await abs_client.update_user(user.abs_user_id, {"password": payload.password})
        except (httpx.HTTPError, TypeError, RuntimeError) as exc:
            raise _abs_error() from exc

    user.password_hash = hash_password(payload.password)
    user.password_changed_at = utcnow()
    user.session_version = int(user.session_version or 0) + 1
    user.updated_at = utcnow()
    session.add(user)
    _audit(session, claims, "admin.user.set_password", user)
    session.commit()
    session.refresh(user)
    return {"user": _serialize(user, None)}


@router.post("/{user_id}/status")
async def set_status(
    user_id: str,
    payload: SetStatusRequest,
    claims: dict[str, Any] = Depends(require_admin),
    session: Session = Depends(get_session),
    abs_factory: Callable[[], AudiobookshelfClient] = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    user = session.get(PortalUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="未找到该用户。")
    if payload.action == "disable":
        _ensure_admin_can_disable_or_delete(session, actor_id=str(claims.get("sub") or ""), target=user)

    is_active = payload.action == "enable"
    expiry = _aware(user.expires_at)
    if is_active and expiry is not None and expiry <= utcnow():
        raise HTTPException(status_code=409, detail="账号已到期，请先延长有效期再启用。")

    user.status = "active" if is_active else "disabled"
    if not is_active:
        user.session_version = int(user.session_version or 0) + 1
    user.updated_at = utcnow()
    session.add(user)
    job = None
    if user.abs_user_id:
        job = enqueue_reconciliation_job(
            session,
            idempotency_key=f"admin-status:{user.id}:{user.session_version}:{payload.action}",
            operation="set_active",
            target_type="portal_user",
            target_id=user.id,
            abs_user_id=user.abs_user_id,
            payload={"isActive": is_active, "source": "admin_status"},
        )
    _audit(session, claims, f"admin.user.{payload.action}", user)
    session.commit()
    synced = True if job is None else await _process_reconciliation_now(session, abs_factory, job)
    session.refresh(user)
    return {
        "user": _serialize(user, {"isActive": is_active} if synced else None),
        "upstreamSynced": synced,
        "reconciliationJobId": job.id if job and not synced else None,
    }


@router.post("/bulk/expiry/preview")
async def bulk_extend_expiry_preview(
    payload: BulkExpiryPreviewRequest,
    _claims: dict[str, Any] = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    users, skipped_admins = _bulk_expiry_candidates(session)
    return {"summary": _bulk_expiry_preview_summary(users, skipped_admins, payload.extendDays)}


@router.post("/bulk/expiry")
async def bulk_extend_expiry(
    payload: BulkExpiryRequest,
    claims: dict[str, Any] = Depends(require_admin),
    session: Session = Depends(get_session),
    abs_factory: Callable[[], AudiobookshelfClient] = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    users, skipped_admins = _bulk_expiry_candidates(session)

    now = utcnow()
    updated: list[PortalUser] = []
    reactivated = 0
    skipped_permanent = 0
    reactivation_jobs: list[ReconciliationJob] = []
    reactivated_user_ids: set[str] = set()
    for user in users:
        base = _aware(user.expires_at)
        if base is None:
            skipped_permanent += 1
            continue
        base = base if base and base > now else now
        user.expires_at = base + timedelta(days=payload.extendDays)
        next_expires = _aware(user.expires_at)
        if user.status == "expired" and next_expires and next_expires > now:
            user.status = "active"
            reactivated += 1
            if user.abs_user_id:
                reactivated_user_ids.add(user.id)
                reactivation_jobs.append(
                    enqueue_reconciliation_job(
                        session,
                        idempotency_key=f"admin-bulk-expiry:{user.id}:{user.expires_at.isoformat()}",
                        operation="set_active",
                        target_type="portal_user",
                        target_id=user.id,
                        abs_user_id=user.abs_user_id,
                        payload={"isActive": True, "source": "admin_bulk_expiry"},
                    )
                )
        user.updated_at = utcnow()
        session.add(user)
        updated.append(user)

    if updated:
        session.add(
            AuditLog(
                actor_user_id=str(claims.get("sub") or ""),
                actor_username=str(claims.get("username") or "admin"),
                action="admin.user.bulk_extend_expiry",
                target_type="portal_user_bulk",
                target_id="all_non_admin",
                detail_json=json.dumps(
                    {
                        "extendDays": payload.extendDays,
                        "reason": payload.reason,
                        "matched": len(users),
                        "updated": len(updated),
                        "reactivated": reactivated,
                        "skippedPermanent": skipped_permanent,
                        "skippedAdmins": len(skipped_admins),
                    },
                    ensure_ascii=False,
                ),
            )
        )
    session.commit()
    synced_jobs = 0
    for job in reactivation_jobs:
        if await _process_reconciliation_now(session, abs_factory, job):
            synced_jobs += 1
    for user in updated:
        session.refresh(user)

    return {
        "summary": {
            "matched": len(users),
            "updated": len(updated),
            "reactivated": reactivated,
            "skippedPermanent": skipped_permanent,
            "skippedAdmins": len(skipped_admins),
        },
        "upstream": {
            "synced": synced_jobs,
            "pending": len(reactivation_jobs) - synced_jobs,
        },
        "users": [
            _serialize(
                user,
                {"isActive": True}
                if user.id in reactivated_user_ids
                and all(
                    job.status == "succeeded"
                    for job in reactivation_jobs
                    if job.target_id == user.id
                )
                else None,
            )
            for user in updated
        ],
    }


@router.post("/{user_id}/expiry")
async def set_expiry(
    user_id: str,
    payload: SetExpiryRequest,
    claims: dict[str, Any] = Depends(require_admin),
    session: Session = Depends(get_session),
    abs_factory: Callable[[], AudiobookshelfClient] = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    user = session.get(PortalUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="未找到该用户。")

    if payload.clear:
        user.expires_at = None
    elif payload.expiresAt is not None:
        user.expires_at = _aware(payload.expiresAt)
    elif payload.extendDays is not None:
        now = utcnow()
        base = _aware(user.expires_at)
        base = base if base and base > now else now
        user.expires_at = base + timedelta(days=payload.extendDays)
    else:
        raise HTTPException(status_code=422, detail="请提供 expiresAt、extendDays 或 clear 之一。")

    now = utcnow()
    expires_at = _aware(user.expires_at)
    should_be_active = user.status != "disabled" and (expires_at is None or expires_at > now)
    should_disable_upstream = bool(expires_at and expires_at <= now)
    upstream_active: bool | None = None

    if should_disable_upstream:
        user.status = "expired"
        user.session_version = int(user.session_version or 0) + 1
        upstream_active = False
    elif should_be_active and user.status == "expired":
        user.status = "active"
        upstream_active = True

    user.updated_at = utcnow()
    session.add(user)
    job = None
    if user.abs_user_id and upstream_active is not None:
        expiry_key = user.expires_at.isoformat() if user.expires_at else "permanent"
        job = enqueue_reconciliation_job(
            session,
            idempotency_key=f"admin-expiry:{user.id}:{expiry_key}:{upstream_active}",
            operation="set_active",
            target_type="portal_user",
            target_id=user.id,
            abs_user_id=user.abs_user_id,
            payload={"isActive": upstream_active, "source": "admin_expiry"},
        )
    _audit(
        session,
        claims,
        "admin.user.set_expiry",
        user,
        {
            "expiresAt": user.expires_at.isoformat() if user.expires_at else None,
            "extendDays": payload.extendDays,
            "clear": payload.clear,
        },
    )
    session.commit()
    synced = True if job is None else await _process_reconciliation_now(session, abs_factory, job)
    session.refresh(user)
    upstream = (
        {"isActive": upstream_active}
        if upstream_active is not None and synced
        else None
    )
    return {
        "user": _serialize(user, upstream),
        "upstreamSynced": synced,
        "reconciliationJobId": job.id if job and not synced else None,
    }


@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    claims: dict[str, Any] = Depends(require_admin),
    session: Session = Depends(get_session),
    abs_factory: Callable[[], AudiobookshelfClient] = Depends(get_abs_client_factory),
) -> dict[str, Any]:
    user = session.get(PortalUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="未找到该用户。")
    _ensure_admin_can_disable_or_delete(session, actor_id=str(claims.get("sub") or ""), target=user)

    user.status = "deleted"
    user.session_version = int(user.session_version or 0) + 1
    user.updated_at = utcnow()
    session.add(user)
    job = None
    if user.abs_user_id:
        job = enqueue_reconciliation_job(
            session,
            idempotency_key=f"admin-delete:{user.id}:{user.session_version}",
            operation="delete_user",
            target_type="portal_user",
            target_id=user.id,
            abs_user_id=user.abs_user_id,
            payload={"source": "admin_delete"},
        )
    _audit(session, claims, "admin.user.delete", user)
    session.commit()
    synced = True if job is None else await _process_reconciliation_now(session, abs_factory, job)
    return {
        "ok": True,
        "id": user_id,
        "upstreamSynced": synced,
        "reconciliationJobId": job.id if job and not synced else None,
    }
