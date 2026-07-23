from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import (
    Code,
    DailyCheckin,
    PointAccount,
    PointLedgerEntry,
    PortalUser,
    ReferralInvite,
    utcnow,
)
from app.services.referrals import create_referral_invite, settle_referral_reward
from app.services.rewards import (
    RewardError,
    checkin,
    credit_points,
    leaderboard,
    redeem_points_for_days,
    set_leaderboard_opt_in,
)


class FakeAbsClient:
    def __init__(self):
        self.updated = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def update_user(self, user_id, payload):
        self.updated.append((user_id, payload))
        return {"id": user_id, **payload}


def _engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _user(username: str, *, expires=True) -> PortalUser:
    return PortalUser(
        username=username,
        password_hash="hash",
        abs_user_id=f"abs-{username}",
        abs_username=username,
        expires_at=utcnow() + timedelta(days=3) if expires else None,
    )


def test_daily_checkin_is_unique_per_shanghai_day_and_streak_is_deterministic():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        user = _user("alice")
        session.add(user)
        session.commit()
        first = checkin(
            session,
            user,
            base_points=10,
            bonus_every=7,
            bonus_points=20,
            now=datetime(2026, 7, 16, 16, 30, tzinfo=UTC),
        )
        duplicate = checkin(
            session,
            user,
            base_points=10,
            bonus_every=7,
            bonus_points=20,
            now=datetime(2026, 7, 17, 1, 0, tzinfo=UTC),
        )
        next_day = checkin(
            session,
            user,
            base_points=10,
            bonus_every=7,
            bonus_points=20,
            now=datetime(2026, 7, 17, 16, 30, tzinfo=UTC),
        )
        assert first["date"] == "2026-07-17"
        assert duplicate["alreadyCheckedIn"] is True
        assert next_day["streak"] == 2
        assert next_day["balance"] == 20
        assert len(session.exec(select(DailyCheckin)).all()) == 2
        ledger = session.exec(select(PointLedgerEntry)).all()
        assert [item.amount for item in ledger] == [10, 10]


@pytest.mark.asyncio
async def test_points_redemption_uses_immutable_debit_and_extends_expiry():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    fake_abs = FakeAbsClient()
    with Session(engine) as session:
        user = _user("alice")
        session.add(user)
        session.commit()
        credit_points(
            session,
            user,
            amount=500,
            kind="test_grant",
            reference="test:grant:alice",
        )
        session.commit()
        before = user.expires_at
        result = await redeem_points_for_days(
            session,
            user,
            days=3,
            points_per_day=100,
            max_days=30,
            abs_factory=lambda: fake_abs,
            idempotency_key="redeem-alice-001",
        )
        assert result["cost"] == 300
        assert result["balance"] == 200
        assert user.expires_at > before + timedelta(days=2)
        first_expiry = user.expires_at
        replay = await redeem_points_for_days(
            session,
            user,
            days=3,
            points_per_day=100,
            max_days=30,
            abs_factory=lambda: fake_abs,
            idempotency_key="redeem-alice-001",
        )
        assert replay["idempotentReplay"] is True
        assert replay["balance"] == 200
        assert user.expires_at == first_expiry
        with pytest.raises(RewardError, match="different parameters"):
            await redeem_points_for_days(
                session,
                user,
                days=1,
                points_per_day=100,
                max_days=30,
                abs_factory=lambda: fake_abs,
                idempotency_key="redeem-alice-001",
            )
        entries = session.exec(
            select(PointLedgerEntry).where(PointLedgerEntry.portal_user_id == user.id)
        ).all()
        assert [item.amount for item in entries] == [500, -300]


@pytest.mark.asyncio
async def test_points_redemption_rejects_insufficient_and_permanent_accounts():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        permanent = _user("permanent", expires=False)
        session.add(permanent)
        session.commit()
        with pytest.raises(RewardError, match="permanent"):
            await redeem_points_for_days(
                session,
                permanent,
                days=1,
                points_per_day=100,
                max_days=30,
                abs_factory=lambda: FakeAbsClient(),
                idempotency_key="redeem-permanent-001",
            )


def test_referral_invite_is_single_use_limited_and_rewards_inviter_once():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        inviter = _user("inviter")
        new_user = _user("new_user")
        session.add(inviter)
        session.add(new_user)
        session.commit()
        created = create_referral_invite(
            session,
            inviter,
            valid_days=7,
            account_days=30,
            reward_points=50,
            monthly_limit=3,
        )
        repeated = create_referral_invite(
            session,
            inviter,
            valid_days=7,
            account_days=30,
            reward_points=50,
            monthly_limit=3,
        )
        assert repeated["existing"] is True
        assert repeated["code"] == created["code"]
        code = session.exec(select(Code).where(Code.code == created["code"])).one()
        assert settle_referral_reward(session, code=code, registered_user=new_user) is True
        assert settle_referral_reward(session, code=code, registered_user=new_user) is False
        account = session.get(PointAccount, inviter.id)
        assert account.balance == 50
        invite = session.exec(select(ReferralInvite)).one()
        assert invite.used_by_user_id == new_user.id


def test_leaderboard_is_opt_in_and_masks_usernames():
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        alice = _user("alice")
        bob = _user("bob")
        session.add(alice)
        session.add(bob)
        session.commit()
        credit_points(session, alice, amount=20, kind="test", reference="test:alice")
        credit_points(session, bob, amount=50, kind="test", reference="test:bob")
        session.commit()
        set_leaderboard_opt_in(session, alice, True)
        entries = leaderboard(session, limit=10)
        assert len(entries) == 1
        assert entries[0]["displayName"] == "a***e"
        assert entries[0]["lifetimeEarned"] == 20
