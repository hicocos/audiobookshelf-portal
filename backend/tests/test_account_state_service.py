from datetime import timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import AccountHold, PortalUser, TelegramGroupMembership, utcnow
from app.services.account_state import clear_account_hold, set_account_hold
from app.services.community import is_group_policy_applicable, report_group_membership


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_a03_multiple_holds_are_explicit_and_clearing_one_does_not_enable_user():
    with _session() as session:
        user = PortalUser(
            id="user-a03",
            username="listener",
            password_hash="hash",
            abs_username="listener",
        )
        session.add(user)
        session.commit()

        set_account_hold(
            session,
            user,
            kind="admin",
            actor="operator",
            source="admin",
            metadata={"reason": "support review"},
        )
        set_account_hold(
            session,
            user,
            kind="group",
            actor="telegram-group-sync",
            source="telegram",
        )
        session.commit()

        assert user.status == "disabled"
        assert {item.kind for item in session.exec(
            select(AccountHold).where(
                AccountHold.portal_user_id == user.id,
                AccountHold.active.is_(True),
            )
        ).all()} == {"admin", "group"}

        clear_account_hold(
            session,
            user,
            kind="group",
            actor="telegram-group-sync",
            source="telegram",
        )
        session.commit()

        assert user.status == "disabled"
        active = session.exec(
            select(AccountHold).where(
                AccountHold.portal_user_id == user.id,
                AccountHold.active.is_(True),
            )
        ).all()
        assert [item.kind for item in active] == ["admin"]


class _AbsClient:
    def __init__(self) -> None:
        self.updated: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def update_user(self, user_id: str, payload: dict):
        self.updated.append((user_id, payload))
        return {"id": user_id, **payload}


@pytest.mark.anyio
async def test_a05_group_rejoin_clears_only_group_hold_and_never_overrides_expiry():
    with _session() as session:
        user = PortalUser(
            id="user-a05",
            username="expired-member",
            password_hash="hash",
            abs_user_id="abs-a05",
            abs_username="expired-member",
            telegram_id="5005",
            telegram_binding_required=True,
            expires_at=utcnow() - timedelta(days=1),
        )
        session.add(user)
        session.commit()
        set_account_hold(
            session,
            user,
            kind="expired",
            actor="worker",
            source="expiry",
        )
        set_account_hold(
            session,
            user,
            kind="group",
            actor="worker",
            source="telegram",
        )
        membership = TelegramGroupMembership(
            portal_user_id=user.id,
            telegram_id="5005",
            group_id="-1005",
            status="disabled",
            disabled_at=utcnow(),
        )
        session.add(membership)
        session.commit()
        upstream = _AbsClient()

        await report_group_membership(
            session,
            user,
            group_id="-1005",
            is_member=True,
            grace_hours=72,
            abs_factory=lambda: upstream,
        )

        session.refresh(user)
        assert user.status == "expired"
        assert upstream.updated == []
        active_kinds = {
            item.kind
            for item in session.exec(
                select(AccountHold).where(
                    AccountHold.portal_user_id == user.id,
                    AccountHold.active.is_(True),
                )
            ).all()
        }
        assert active_kinds == {"expired"}


def test_a04_group_policy_scope_is_fixed_to_new_users_only():
    old_user = PortalUser(
        username="grandfathered",
        password_hash="hash",
        abs_username="grandfathered",
        telegram_id="4001",
        telegram_binding_required=False,
    )
    new_user = PortalUser(
        username="new-user",
        password_hash="hash",
        abs_username="new-user",
        telegram_id="4002",
        telegram_binding_required=True,
    )
    admin = PortalUser(
        username="operator",
        password_hash="hash",
        abs_username="operator",
        telegram_id="4003",
        telegram_binding_required=True,
        role="admin",
    )
    settings = {
        "groupMembershipEnabled": True,
        "groupPolicyScope": "new_users_only",
    }

    assert is_group_policy_applicable(old_user, settings) is False
    assert is_group_policy_applicable(new_user, settings) is True
    assert is_group_policy_applicable(admin, settings) is False
