from datetime import timedelta

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import (
    AuditLog,
    PortalUser,
    TelegramGroupMembership,
    TelegramNotification,
    utcnow,
)
from app.services.community import enforce_group_grace_periods, report_group_membership


class FakeAbsClient:
    def __init__(self) -> None:
        self.updates: list[tuple[str, dict[str, bool]]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    async def update_user(self, user_id: str, payload: dict[str, bool]):
        self.updates.append((user_id, payload))
        return {"id": user_id, **payload}


def make_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def seed_user(
    session: Session,
    *,
    role: str = "user",
    telegram_binding_required: bool = True,
) -> PortalUser:
    user = PortalUser(
        username=f"community-{role}",
        username_normalized=f"community-{role}",
        password_hash="test",
        abs_user_id=f"abs-{role}",
        abs_username=f"community-{role}",
        telegram_id=f"tg-{role}",
        telegram_bound_at=utcnow(),
        expires_at=utcnow() + timedelta(days=30),
        role=role,
        telegram_binding_required=telegram_binding_required,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_legacy_exempt_user_is_never_put_on_account_disable_grace():
    engine = make_engine()
    fake_abs = FakeAbsClient()
    with Session(engine) as session:
        user = seed_user(session, telegram_binding_required=False)
        membership = await report_group_membership(
            session,
            user,
            group_id="-100123",
            is_member=False,
            grace_hours=72,
            abs_factory=lambda: fake_abs,
        )

        assert membership.status == "exempt"
        assert membership.grace_expires_at is None
        assert session.exec(select(TelegramNotification)).all() == []
        result = await enforce_group_grace_periods(session, fake_abs)
        session.refresh(user)
        assert result == {"checked": 0, "disabled": 0, "failed": 0}
        assert user.status == "active"
        assert fake_abs.updates == []


@pytest.mark.asyncio
async def test_leave_starts_one_grace_period_and_rejoin_clears_it():
    engine = make_engine()
    fake_abs = FakeAbsClient()
    with Session(engine) as session:
        user = seed_user(session)
        first = await report_group_membership(
            session,
            user,
            group_id="-100123",
            is_member=False,
            grace_hours=72,
            abs_factory=lambda: fake_abs,
        )
        original_expiry = first.grace_expires_at
        second = await report_group_membership(
            session,
            user,
            group_id="-100123",
            is_member=False,
            grace_hours=72,
            abs_factory=lambda: fake_abs,
        )
        assert second.status == "grace"
        assert second.grace_expires_at == original_expiry
        assert len(session.exec(select(TelegramNotification)).all()) == 1

        joined = await report_group_membership(
            session,
            user,
            group_id="-100123",
            is_member=True,
            grace_hours=72,
            abs_factory=lambda: fake_abs,
        )
        assert joined.status == "member"
        assert joined.grace_expires_at is None
        assert fake_abs.updates == []


@pytest.mark.asyncio
async def test_expired_grace_disables_and_rejoin_restores_group_disabled_user():
    engine = make_engine()
    fake_abs = FakeAbsClient()
    with Session(engine) as session:
        user = seed_user(session)
        membership = await report_group_membership(
            session,
            user,
            group_id="-100123",
            is_member=False,
            grace_hours=72,
            abs_factory=lambda: fake_abs,
        )
        membership.grace_expires_at = utcnow() - timedelta(seconds=1)
        session.add(membership)
        session.commit()

        result = await enforce_group_grace_periods(session, fake_abs)
        session.refresh(user)
        session.refresh(membership)
        assert result == {"checked": 1, "disabled": 1, "failed": 0}
        assert user.status == "disabled"
        assert membership.status == "disabled"
        assert fake_abs.updates == [(user.abs_user_id, {"isActive": False})]

        joined = await report_group_membership(
            session,
            user,
            group_id="-100123",
            is_member=True,
            grace_hours=72,
            abs_factory=lambda: fake_abs,
        )
        session.refresh(user)
        assert joined.status == "member"
        assert user.status == "active"
        assert fake_abs.updates[-1] == (user.abs_user_id, {"isActive": True})
        actions = [item.action for item in session.exec(select(AuditLog)).all()]
        assert "telegram.group.disable_after_grace" in actions
        assert "telegram.group.rejoin_enable" in actions


@pytest.mark.asyncio
async def test_rejoin_does_not_override_a_later_manual_disable():
    engine = make_engine()
    fake_abs = FakeAbsClient()
    with Session(engine) as session:
        user = seed_user(session)
        membership = TelegramGroupMembership(
            portal_user_id=user.id,
            telegram_id=str(user.telegram_id),
            group_id="-100123",
            status="disabled",
            disabled_at=utcnow() - timedelta(hours=1),
        )
        user.status = "disabled"
        user.updated_at = utcnow()
        session.add(user)
        session.add(membership)
        session.commit()

        joined = await report_group_membership(
            session,
            user,
            group_id="-100123",
            is_member=True,
            grace_hours=72,
            abs_factory=lambda: fake_abs,
        )
        session.refresh(user)
        assert joined.status == "member"
        assert user.status == "disabled"
        assert fake_abs.updates == []


@pytest.mark.asyncio
async def test_grace_sweep_queues_deduplicated_24h_and_6h_reminders():
    engine = make_engine()
    fake_abs = FakeAbsClient()
    with Session(engine) as session:
        user = seed_user(session)
        membership = await report_group_membership(
            session,
            user,
            group_id="-100123",
            is_member=False,
            grace_hours=72,
            abs_factory=lambda: fake_abs,
        )
        membership.grace_expires_at = utcnow() + timedelta(hours=23)
        session.add(membership)
        session.commit()

        await enforce_group_grace_periods(session, fake_abs)
        await enforce_group_grace_periods(session, fake_abs)
        reminders = session.exec(
            select(TelegramNotification).where(
                TelegramNotification.kind == "group_grace_reminder"
            )
        ).all()
        assert len(reminders) == 1
        assert "24 小时" in reminders[0].message

        membership.grace_expires_at = utcnow() + timedelta(hours=5)
        session.add(membership)
        session.commit()
        await enforce_group_grace_periods(session, fake_abs)
        await enforce_group_grace_periods(session, fake_abs)
        reminders = session.exec(
            select(TelegramNotification).where(
                TelegramNotification.kind == "group_grace_reminder"
            ).order_by(TelegramNotification.created_at)
        ).all()
        assert len(reminders) == 2
        assert "6 小时" in reminders[1].message
