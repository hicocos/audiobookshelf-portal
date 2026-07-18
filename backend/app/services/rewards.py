import json
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import (
    AuditLog,
    DailyCheckin,
    PointAccount,
    PointLedgerEntry,
    PortalUser,
    utcnow,
)
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
    existing = session.exec(
        select(PointLedgerEntry).where(PointLedgerEntry.reference == redemption_id)
    ).first()
    if existing is not None:
        session.refresh(user)
        return {
            "days": days,
            "cost": abs(existing.amount),
            "balance": existing.balance_after,
            "expiresAt": _aware(user.expires_at).isoformat(),
            "upstreamReactivated": True,
            "idempotentReplay": True,
        }
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
    if user.status == "expired":
        user.status = "active"
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
    try:
        session.commit()
    except IntegrityError:
        # Another request with the same operation key committed first. Roll
        # back this attempt and return that result without extending twice.
        session.rollback()
        existing = session.exec(
            select(PointLedgerEntry).where(PointLedgerEntry.reference == redemption_id)
        ).one()
        current_user = session.get(PortalUser, user.id)
        return {
            "days": days,
            "cost": abs(existing.amount),
            "balance": existing.balance_after,
            "expiresAt": _aware(current_user.expires_at).isoformat(),
            "upstreamReactivated": True,
            "idempotentReplay": True,
        }
    upstream_reactivated = True
    if was_expired and user.abs_user_id:
        try:
            async with abs_factory() as abs_client:
                await abs_client.update_user(user.abs_user_id, {"isActive": True})
        except (httpx.HTTPError, TypeError, RuntimeError):
            upstream_reactivated = False
            enqueue_reconciliation_job(
                session,
                idempotency_key=redemption_id,
                operation="set_active",
                target_type="portal_user",
                target_id=user.id,
                abs_user_id=user.abs_user_id,
                payload={"isActive": True, "source": "points_redemption"},
            )
            session.commit()
    account = session.get(PointAccount, user.id)
    return {
        "days": days,
        "cost": cost,
        "balance": account.balance,
        "expiresAt": user.expires_at.isoformat(),
        "upstreamReactivated": upstream_reactivated,
        "idempotentReplay": False,
    }


def points_summary(session: Session, user: PortalUser) -> dict[str, Any]:
    account = get_point_account(session, user)
    latest = session.exec(
        select(DailyCheckin)
        .where(DailyCheckin.portal_user_id == user.id)
        .order_by(DailyCheckin.local_date.desc())
    ).first()
    history = session.exec(
        select(PointLedgerEntry)
        .where(PointLedgerEntry.portal_user_id == user.id)
        .order_by(PointLedgerEntry.created_at.desc())
        .limit(10)
    ).all()
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
                "createdAt": item.created_at.isoformat(),
            }
            for item in history
        ],
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
