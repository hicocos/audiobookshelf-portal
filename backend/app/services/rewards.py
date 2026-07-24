import json
import hashlib
import base64
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import (
    AuditLog,
    AccountOperation,
    DailyCheckin,
    PointAccount,
    PointLedgerEntry,
    PortalUser,
    utcnow,
)
from app.services.account_state import sync_expiry_hold
from app.services.reconciliation import enqueue_reconciliation_job

SHANGHAI = ZoneInfo("Asia/Shanghai")


class RewardError(ValueError):
    pass


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def get_point_account(session: Session, user: PortalUser) -> PointAccount:
    account = session.get(PointAccount, user.id)
    if account is None:
        account = PointAccount(portal_user_id=user.id)
        session.add(account)
        session.flush()
    return account


def credit_points(
    session: Session,
    user: PortalUser,
    *,
    amount: int,
    kind: str,
    reference: str,
    detail: dict[str, Any] | None = None,
) -> PointLedgerEntry:
    if amount < 0:
        raise RewardError("credit amount must not be negative")
    existing = session.exec(
        select(PointLedgerEntry).where(PointLedgerEntry.reference == reference)
    ).first()
    if existing is not None:
        return existing
    get_point_account(session, user)
    result = session.exec(
        update(PointAccount)
        .where(PointAccount.portal_user_id == user.id)
        .values(
            balance=PointAccount.balance + amount,
            lifetime_earned=PointAccount.lifetime_earned + amount,
            updated_at=utcnow(),
        )
    )
    if result.rowcount != 1:
        raise RewardError("point account update failed")
    session.flush()
    account = session.get(PointAccount, user.id)
    session.refresh(account)
    entry = PointLedgerEntry(
        portal_user_id=user.id,
        amount=amount,
        balance_after=account.balance,
        kind=kind,
        reference=reference,
        detail_json=json.dumps(detail, ensure_ascii=False) if detail else None,
    )
    session.add(account)
    session.add(entry)
    session.flush()
    return entry


def debit_points(
    session: Session,
    user: PortalUser,
    *,
    amount: int,
    kind: str,
    reference: str,
    detail: dict[str, Any] | None = None,
) -> PointLedgerEntry:
    if amount <= 0:
        raise RewardError("debit amount must be positive")
    existing = session.exec(
        select(PointLedgerEntry).where(PointLedgerEntry.reference == reference)
    ).first()
    if existing is not None:
        return existing
    get_point_account(session, user)
    result = session.exec(
        update(PointAccount)
        .where(
            PointAccount.portal_user_id == user.id,
            PointAccount.balance >= amount,
        )
        .values(
            balance=PointAccount.balance - amount,
            updated_at=utcnow(),
        )
    )
    if result.rowcount != 1:
        raise RewardError("insufficient points")
    session.flush()
    account = session.get(PointAccount, user.id)
    session.refresh(account)
    entry = PointLedgerEntry(
        portal_user_id=user.id,
        amount=-amount,
        balance_after=account.balance,
        kind=kind,
        reference=reference,
        detail_json=json.dumps(detail, ensure_ascii=False) if detail else None,
    )
    session.add(entry)
    session.flush()
    return entry


def checkin(
    session: Session,
    user: PortalUser,
    *,
    base_points: int,
    bonus_every: int,
    bonus_points: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or utcnow()
    local_date = now.astimezone(SHANGHAI).date()
    date_key = local_date.isoformat()
    existing = session.exec(
        select(DailyCheckin).where(
            DailyCheckin.portal_user_id == user.id,
            DailyCheckin.local_date == date_key,
        )
    ).first()
    if existing is not None:
        account = get_point_account(session, user)
        return {
            "alreadyCheckedIn": True,
            "date": date_key,
            "streak": existing.streak,
            "pointsAwarded": existing.points_awarded,
            "balance": account.balance,
        }
    previous = session.exec(
        select(DailyCheckin)
        .where(DailyCheckin.portal_user_id == user.id)
        .order_by(DailyCheckin.local_date.desc())
    ).first()
    yesterday = (local_date - timedelta(days=1)).isoformat()
    streak = previous.streak + 1 if previous and previous.local_date == yesterday else 1
    award = max(1, base_points)
    if bonus_every > 0 and streak % bonus_every == 0:
        award += max(0, bonus_points)
    entry = credit_points(
        session,
        user,
        amount=award,
        kind="daily_checkin",
        reference=f"checkin:{user.id}:{date_key}",
        detail={"date": date_key, "streak": streak},
    )
    item = DailyCheckin(
        portal_user_id=user.id,
        local_date=date_key,
        streak=streak,
        points_awarded=award,
        ledger_entry_id=entry.id,
    )
    session.add(item)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.exec(
            select(DailyCheckin).where(
                DailyCheckin.portal_user_id == user.id,
                DailyCheckin.local_date == date_key,
            )
        ).one()
        account = get_point_account(session, user)
        return {
            "alreadyCheckedIn": True,
            "date": date_key,
            "streak": existing.streak,
            "pointsAwarded": existing.points_awarded,
            "balance": account.balance,
        }
    account = session.get(PointAccount, user.id)
    return {
        "alreadyCheckedIn": False,
        "date": date_key,
        "streak": streak,
        "pointsAwarded": award,
        "balance": account.balance,
    }


async def redeem_points_for_days(
    session: Session,
    user: PortalUser,
    *,
    days: int,
    points_per_day: int,
    max_days: int,
    abs_factory: Any,
    idempotency_key: str,
) -> dict[str, Any]:
    if days < 1 or days > max_days:
        raise RewardError(f"redeem days must be between 1 and {max_days}")
    if user.expires_at is None:
        raise RewardError("permanent account cannot redeem expiry days")
    normalized_key = idempotency_key.strip()
    if not normalized_key or len(normalized_key) > 80:
        raise RewardError("invalid idempotency key")
    cost = days * points_per_day
    redemption_id = f"points-redeem:{user.id}:{normalized_key}"
    request_hash = hashlib.sha256(
        json.dumps(
            {"days": days, "pointsPerDay": points_per_day},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    operation = session.exec(
        select(AccountOperation).where(
            AccountOperation.idempotency_key == redemption_id
        )
    ).first()
    if operation is not None:
        if operation.request_hash != request_hash:
            raise RewardError("idempotency key was already used with different parameters")
        if operation.result_json:
            try:
                result = json.loads(operation.result_json)
            except (json.JSONDecodeError, TypeError) as exc:
                raise RewardError("stored redemption result is invalid") from exc
            return {**result, "idempotentReplay": True}
        existing_entry = session.exec(
            select(PointLedgerEntry).where(PointLedgerEntry.reference == redemption_id)
        ).first()
        if existing_entry is not None:
            job_id = operation.reconciliation_job_id
            return {
                "operationId": operation.id,
                "phase": operation.phase,
                "days": days,
                "cost": abs(existing_entry.amount),
                "balance": existing_entry.balance_after,
                "expiresAt": _aware(user.expires_at).isoformat(),
                "upstreamReactivated": False,
                "reconciliationJobId": job_id,
                "idempotentReplay": True,
            }
    existing = session.exec(
        select(PointLedgerEntry).where(PointLedgerEntry.reference == redemption_id)
    ).first()
    if existing is not None:
        try:
            original_detail = json.loads(existing.detail_json or "{}")
        except (json.JSONDecodeError, TypeError):
            original_detail = {}
        if original_detail.get("days") != days or original_detail.get("pointsPerDay") != points_per_day:
            raise RewardError("idempotency key was already used with different parameters")
        session.refresh(user)
        return {
            "days": int(original_detail["days"]),
            "cost": abs(existing.amount),
            "balance": existing.balance_after,
            "expiresAt": _aware(user.expires_at).isoformat(),
            "upstreamReactivated": False,
            "reconciliationJobId": None,
            "idempotentReplay": True,
        }
    operation = AccountOperation(
        kind="points_redemption",
        portal_user_id=user.id,
        idempotency_key=redemption_id,
        phase="applying_local",
        request_hash=request_hash,
    )
    session.add(operation)
    debit_points(
        session,
        user,
        amount=cost,
        kind="redeem_expiry_days",
        reference=redemption_id,
        detail={"days": days, "pointsPerDay": points_per_day},
    )
    now = utcnow()
    current = _aware(user.expires_at)
    base = current if current and current > now else now
    user.expires_at = base + timedelta(days=days)
    was_expired = user.status == "expired" or bool(current and current <= now)
    sync_expiry_hold(
        session,
        user,
        actor=user.username,
        source="points_redemption",
        now=now,
    )
    user.updated_at = now
    session.add(user)
    session.add(
        AuditLog(
            actor_user_id=user.id,
            actor_username=user.username,
            action="telegram.points.redeem_days",
            target_type="portal_user",
            target_id=user.id,
            detail_json=json.dumps({"days": days, "cost": cost}),
        )
    )
    job = None
    if was_expired and user.status == "active" and user.abs_user_id:
        job = enqueue_reconciliation_job(
            session,
            idempotency_key=redemption_id,
            operation="set_active",
            target_type="portal_user",
            target_id=user.id,
            abs_user_id=user.abs_user_id,
            payload={"isActive": True, "source": "points_redemption"},
        )
        session.flush()
        operation.reconciliation_job_id = job.id
    operation.phase = "local_committed"
    operation.updated_at = now
    session.add(operation)
    try:
        session.commit()
    except IntegrityError:
        # Another request with the same operation key committed first. Roll
        # back this attempt and return that result without extending twice.
        session.rollback()
        existing = session.exec(
            select(PointLedgerEntry).where(PointLedgerEntry.reference == redemption_id)
        ).one()
        try:
            original_detail = json.loads(existing.detail_json or "{}")
        except (json.JSONDecodeError, TypeError):
            original_detail = {}
        if original_detail.get("days") != days or original_detail.get("pointsPerDay") != points_per_day:
            raise RewardError("idempotency key was already used with different parameters")
        current_user = session.get(PortalUser, user.id)
        return {
            "operationId": operation.id,
            "phase": "completed",
            "days": int(original_detail["days"]),
            "cost": abs(existing.amount),
            "balance": existing.balance_after,
            "expiresAt": _aware(current_user.expires_at).isoformat(),
            "upstreamReactivated": False,
            "reconciliationJobId": None,
            "idempotentReplay": True,
        }
    upstream_reactivated = True
    if job is not None:
        try:
            async with abs_factory() as abs_client:
                await abs_client.update_user(user.abs_user_id, {"isActive": True})
        except (httpx.HTTPError, TypeError, RuntimeError):
            upstream_reactivated = False
        else:
            completed_at = utcnow()
            job.status = "succeeded"
            job.attempts = int(job.attempts or 0) + 1
            job.last_error = None
            job.succeeded_at = completed_at
            job.updated_at = completed_at
            session.add(job)
    account = session.get(PointAccount, user.id)
    result = {
        "operationId": operation.id,
        "phase": "completed" if upstream_reactivated else "reconciliation_pending",
        "days": days,
        "cost": cost,
        "balance": account.balance,
        "expiresAt": user.expires_at.isoformat(),
        "upstreamReactivated": upstream_reactivated,
        "reconciliationJobId": job.id if job and not upstream_reactivated else None,
        "idempotentReplay": False,
    }
    operation.phase = result["phase"]
    operation.status = "completed"
    operation.result_json = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    operation.completed_at = utcnow()
    operation.updated_at = operation.completed_at
    session.add(operation)
    session.commit()
    return result


POINT_REASON_LABELS = {
    "daily_checkin": "每日签到",
    "referral_reward": "邀请奖励",
    "redeem_expiry_days": "兑换有效期",
    "admin_adjustment": "管理员调整",
    "test_grant": "积分发放",
}


def _ledger_cursor(entry: PointLedgerEntry) -> str:
    raw = json.dumps(
        {"createdAt": _aware(entry.created_at).isoformat(), "id": entry.id},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_ledger_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode())
        return datetime.fromisoformat(value["createdAt"]), str(value["id"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RewardError("invalid ledger cursor") from exc


def points_summary(
    session: Session,
    user: PortalUser,
    *,
    limit: int = 10,
    cursor: str | None = None,
) -> dict[str, Any]:
    account = get_point_account(session, user)
    latest = session.exec(
        select(DailyCheckin)
        .where(DailyCheckin.portal_user_id == user.id)
        .order_by(DailyCheckin.local_date.desc())
    ).first()
    page_size = max(1, min(limit, 50))
    history_query = select(PointLedgerEntry).where(PointLedgerEntry.portal_user_id == user.id)
    if cursor:
        created_at, entry_id = _decode_ledger_cursor(cursor)
        history_query = history_query.where(
            (PointLedgerEntry.created_at < created_at)
            | ((PointLedgerEntry.created_at == created_at) & (PointLedgerEntry.id < entry_id))
        )
    history = session.exec(
        history_query.order_by(PointLedgerEntry.created_at.desc(), PointLedgerEntry.id.desc())
        .limit(page_size + 1)
    ).all()
    has_more = len(history) > page_size
    history = history[:page_size]
    return {
        "balance": account.balance,
        "lifetimeEarned": account.lifetime_earned,
        "leaderboardOptIn": account.leaderboard_opt_in,
        "streak": latest.streak if latest else 0,
        "lastCheckinDate": latest.local_date if latest else None,
        "history": [
            {
                "amount": item.amount,
                "balanceAfter": item.balance_after,
                "kind": item.kind,
                "reasonLabel": POINT_REASON_LABELS.get(item.kind, "积分变动"),
                "createdAt": item.created_at.isoformat(),
            }
            for item in history
        ],
        "nextCursor": _ledger_cursor(history[-1]) if has_more and history else None,
    }


def set_leaderboard_opt_in(session: Session, user: PortalUser, enabled: bool) -> dict[str, Any]:
    account = get_point_account(session, user)
    account.leaderboard_opt_in = enabled
    account.updated_at = utcnow()
    session.add(account)
    session.commit()
    return {"enabled": enabled}


def _masked_username(value: str) -> str:
    if len(value) <= 2:
        return value[0] + "*" if value else "***"
    return value[0] + "*" * min(5, len(value) - 2) + value[-1]


def leaderboard(session: Session, *, limit: int) -> list[dict[str, Any]]:
    rows = session.exec(
        select(PointAccount, PortalUser)
        .join(PortalUser, PortalUser.id == PointAccount.portal_user_id)
        .where(
            PointAccount.leaderboard_opt_in.is_(True),
            PortalUser.status.in_(["active", "expired"]),
            PortalUser.role.notin_(["admin", "root"]),
        )
        .order_by(PointAccount.lifetime_earned.desc(), PointAccount.updated_at)
        .limit(max(3, min(limit, 50)))
    ).all()
    return [
        {
            "rank": index,
            "displayName": _masked_username(user.username),
            "lifetimeEarned": account.lifetime_earned,
        }
        for index, (account, user) in enumerate(rows, start=1)
    ]
