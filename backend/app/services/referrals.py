from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.models import Code, CodeRedemption, PortalUser, ReferralInvite, utcnow
from app.services.codes import generate_code
from app.services.rewards import credit_points
from app.services.telegram_notifications import enqueue_notification

SHANGHAI = ZoneInfo("Asia/Shanghai")


class ReferralError(ValueError):
    pass


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def create_referral_invite(
    session: Session,
    inviter: PortalUser,
    *,
    valid_days: int,
    account_days: int,
    reward_points: int,
    monthly_limit: int,
) -> dict[str, Any]:
    now = utcnow()
    active = session.exec(
        select(ReferralInvite)
        .where(
            ReferralInvite.inviter_user_id == inviter.id,
            ReferralInvite.used_by_user_id.is_(None),
            ReferralInvite.expires_at > now,
        )
        .order_by(ReferralInvite.created_at.desc())
    ).first()
    if active is not None:
        code = session.get(Code, active.code_id)
        if code is not None and code.status == "active" and code.used_count < code.max_uses:
            return _public_invite(active, code, existing=True)

    local_now = now.astimezone(SHANGHAI)
    month_start_local = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_start = month_start_local.astimezone(UTC)
    created_this_month = session.exec(
        select(ReferralInvite).where(
            ReferralInvite.inviter_user_id == inviter.id,
            ReferralInvite.created_at >= month_start,
        )
    ).all()
    if len(created_this_month) >= monthly_limit:
        raise ReferralError("monthly referral invite limit reached")

    expires_at = now + timedelta(days=valid_days)
    code = generate_code(
        session,
        type="register",
        duration_days=account_days,
        created_by=inviter.id,
        max_uses=1,
        expires_at=expires_at,
        note="telegram referral invite",
        commit=False,
    )
    invite = ReferralInvite(
        inviter_user_id=inviter.id,
        code_id=code.id,
        reward_points=reward_points,
        expires_at=expires_at,
    )
    session.add(invite)
    session.commit()
    session.refresh(invite)
    return _public_invite(invite, code, existing=False)


def _public_invite(invite: ReferralInvite, code: Code, *, existing: bool) -> dict[str, Any]:
    return {
        "code": code.code,
        "expiresAt": _aware(invite.expires_at).isoformat(),
        "accountDays": code.duration_days,
        "rewardPoints": invite.reward_points,
        "existing": existing,
    }


def settle_referral_reward(
    session: Session,
    *,
    code: Code,
    registered_user: PortalUser,
) -> bool:
    invite = session.exec(
        select(ReferralInvite).where(ReferralInvite.code_id == code.id)
    ).first()
    if invite is None or invite.settled_at is not None:
        return False
    if invite.inviter_user_id == registered_user.id:
        return False
    inviter = session.get(PortalUser, invite.inviter_user_id)
    if inviter is None:
        return False
    credit_points(
        session,
        inviter,
        amount=invite.reward_points,
        kind="referral_reward",
        reference=f"referral:{invite.id}",
        detail={"registeredUserId": registered_user.id},
    )
    invite.used_by_user_id = registered_user.id
    invite.settled_at = utcnow()
    session.add(invite)
    session.commit()
    if inviter.telegram_id:
        enqueue_notification(
            session,
            dedupe_key=f"referral-reward:{invite.id}",
            telegram_id=inviter.telegram_id,
            kind="referral_reward",
            message=f"你的邀请已成功开户注册，获得 {invite.reward_points} 积分。",
        )
    return True


def settle_pending_referrals(session: Session) -> int:
    pending = session.exec(
        select(ReferralInvite).where(ReferralInvite.settled_at.is_(None))
    ).all()
    settled = 0
    for invite in pending:
        code = session.get(Code, invite.code_id)
        if code is None or code.used_count < 1:
            continue
        redemption = session.exec(
            select(CodeRedemption)
            .where(CodeRedemption.code_id == code.id)
            .order_by(CodeRedemption.created_at.desc())
        ).first()
        if redemption is None:
            continue
        registered_user = session.exec(
            select(PortalUser).where(
                PortalUser.username_normalized == redemption.username_snapshot.casefold()
            )
        ).first()
        if registered_user and settle_referral_reward(
            session,
            code=code,
            registered_user=registered_user,
        ):
            settled += 1
    return settled
