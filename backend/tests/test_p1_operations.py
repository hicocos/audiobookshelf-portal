from datetime import timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.config import Settings
from app.models import AccountOperation, Code, PointAccount, PointLedgerEntry, PortalUser, utcnow
from app.services.rewards import redeem_points_for_days
from app.services.provisioning import compensate_orphan_abs_user
from app.services.password_sync import begin_password_sync, retry_password_sync
from app.security import verify_password
from app.routers.me import sync_upstream_account_status
from app.services.bulk_operations import (
    BulkPreviewError,
    create_bulk_expiry_preview,
    validate_bulk_expiry_preview,
)
from app.services.inactivity_policy import (
    activate_due_inactivity_policies,
    cancel_inactivity_policy,
    confirm_inactivity_policy,
    preview_inactivity_policy,
)
from app.services.settings import get_public_settings
from app.services.renewal_operations import (
    RenewalPreviewError,
    create_renewal_preview,
    validate_renewal_preview,
)
from app.services.telegram_binding import (
    activate_binding_operation,
    bind_telegram_user,
    create_bind_token,
)


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_a11_renewal_preview_is_read_only_and_stale_state_cannot_be_confirmed():
    with _session() as session:
        user = PortalUser(
            id="user-a11",
            username="listener-a11",
            password_hash="hash",
            abs_username="listener-a11",
            expires_at=utcnow() + timedelta(days=3),
        )
        code = Code(
            id="code-a11",
            code="RENEW-A11",
            type="renew",
            duration_days=30,
            max_uses=5,
        )
        session.add(user)
        session.add(code)
        session.commit()

        preview = create_renewal_preview(session, user, code.code)
        session.refresh(code)
        assert code.used_count == 0
        assert preview["durationDays"] == 30
        assert preview["currentExpiresAt"]
        assert preview["nextExpiresAt"]
        assert preview["previewToken"]

        user.expires_at = user.expires_at + timedelta(days=1)
        user.updated_at = utcnow()
        session.add(user)
        session.commit()

        with pytest.raises(RenewalPreviewError, match="state changed"):
            validate_renewal_preview(
                session,
                user,
                preview_token=preview["previewToken"],
                operation_id=preview["operationId"],
            )
        session.refresh(code)
        assert code.used_count == 0


class _FailingAbs:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def update_user(self, _user_id: str, _payload: dict):
        raise RuntimeError("upstream unavailable")

    async def list_users(self):
        raise RuntimeError("upstream unavailable")


class _WorkingAbs:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def update_user(self, user_id: str, payload: dict):
        return {"id": user_id, **payload}


@pytest.mark.anyio
async def test_a12_points_operation_replay_keeps_exact_original_upstream_result():
    with _session() as session:
        user = PortalUser(
            id="user-a12",
            username="listener-a12",
            password_hash="hash",
            abs_user_id="abs-a12",
            abs_username="listener-a12",
            status="expired",
            expires_at=utcnow() - timedelta(days=1),
        )
        session.add(user)
        session.add(PointAccount(portal_user_id=user.id, balance=1000))
        session.commit()

        first = await redeem_points_for_days(
            session,
            user,
            days=2,
            points_per_day=100,
            max_days=30,
            abs_factory=lambda: _FailingAbs(),
            idempotency_key="points-a12-operation",
        )
        replay = await redeem_points_for_days(
            session,
            user,
            days=2,
            points_per_day=100,
            max_days=30,
            abs_factory=lambda: _WorkingAbs(),
            idempotency_key="points-a12-operation",
        )

        assert first["upstreamReactivated"] is False
        assert replay["upstreamReactivated"] is False
        assert replay["reconciliationJobId"] == first["reconciliationJobId"]
        assert replay["idempotentReplay"] is True
        assert len(session.exec(
            select(PointLedgerEntry).where(
                PointLedgerEntry.portal_user_id == user.id,
                PointLedgerEntry.kind == "redeem_expiry_days",
            )
        ).all()) == 1


@pytest.mark.anyio
async def test_a07_binding_and_activation_use_one_retryable_persistent_operation():
    settings = Settings(
        JWT_SECRET="test-secret-at-least-32-bytes-long",
        TELEGRAM_BIND_CODE_TTL_MINUTES=10,
    )
    with _session() as session:
        user = PortalUser(
            id="user-a07",
            username="listener-a07",
            password_hash="hash",
            abs_user_id="abs-a07",
            abs_username="listener-a07",
            status="pending",
            telegram_binding_required=True,
            expires_at=utcnow() + timedelta(days=30),
        )
        session.add(user)
        session.commit()
        code, _token = create_bind_token(session, user, settings=settings)

        bound = bind_telegram_user(
            session,
            code=code,
            telegram_id="7007",
            telegram_username="listener_a07",
            settings=settings,
            operation_id="binding-a07",
        )
        operation = session.exec(
            select(AccountOperation).where(
                AccountOperation.kind == "telegram_binding_activation",
                AccountOperation.portal_user_id == user.id,
            )
        ).one()
        assert operation.idempotency_key == "binding-a07"
        assert operation.phase == "binding_saved"

        pending = await activate_binding_operation(
            session,
            bound,
            operation=operation,
            abs_factory=lambda: _FailingAbs(),
        )
        assert pending.phase == "activation_pending"
        assert bound.status == "pending"

        completed = await activate_binding_operation(
            session,
            bound,
            operation=operation,
            abs_factory=lambda: _WorkingAbs(),
        )
        session.refresh(bound)
        assert completed.id == operation.id
        assert completed.phase == "completed"
        assert bound.status == "active"
        assert len(session.exec(
            select(AccountOperation).where(
                AccountOperation.kind == "telegram_binding_activation",
                AccountOperation.portal_user_id == user.id,
            )
        ).all()) == 1


@pytest.mark.anyio
async def test_a08_failed_abs_cleanup_always_creates_one_durable_compensation_job():
    with _session() as session:
        first = await compensate_orphan_abs_user(
            session,
            abs_factory=lambda: _FailingAbs(),
            abs_user_id="abs-orphan-a08",
            username="orphan-a08",
            source="telegram_registration",
        )
        second = await compensate_orphan_abs_user(
            session,
            abs_factory=lambda: _FailingAbs(),
            abs_user_id="abs-orphan-a08",
            username="orphan-a08",
            source="admin_create",
        )

        assert first["compensated"] is False
        assert first["reconciliationJobId"] == second["reconciliationJobId"]
        from app.models import ReconciliationJob

        jobs = session.exec(
            select(ReconciliationJob).where(
                ReconciliationJob.target_type == "provisioning_orphan",
                ReconciliationJob.abs_user_id == "abs-orphan-a08",
            )
        ).all()
        assert len(jobs) == 1


@pytest.mark.anyio
async def test_a09_password_sync_never_stores_plaintext_and_can_retry_after_abs_failure():
    with _session() as session:
        user = PortalUser(
            id="user-a09",
            username="listener-a09",
            password_hash="old-hash",
            abs_user_id="abs-a09",
            abs_username="listener-a09",
        )
        session.add(user)
        session.commit()
        new_password = "NewSecret-A09"

        operation = begin_password_sync(
            session,
            user,
            new_password=new_password,
            idempotency_key="password-a09",
            actor="listener-a09",
        )
        pending = await retry_password_sync(
            session,
            user,
            operation=operation,
            new_password=new_password,
            abs_factory=lambda: _FailingAbs(),
        )

        session.refresh(user)
        assert verify_password(new_password, user.password_hash)
        assert pending.phase == "upstream_pending"
        assert new_password not in str(pending.model_dump())

        completed = await retry_password_sync(
            session,
            user,
            operation=operation,
            new_password=new_password,
            abs_factory=lambda: _WorkingAbs(),
        )
        assert completed.id == operation.id
        assert completed.phase == "completed"
        assert completed.status == "completed"


@pytest.mark.anyio
async def test_a13_abs_outage_is_explicit_and_never_masquerades_as_missing_user():
    with _session() as session:
        user = PortalUser(
            id="user-a13",
            username="listener-a13",
            password_hash="hash",
            abs_user_id="abs-a13",
            abs_username="listener-a13",
            status="active",
        )
        session.add(user)
        session.commit()

        result = await sync_upstream_account_status(
            user,
            session,
            lambda: _FailingAbs(),
        )

        session.refresh(user)
        assert result.upstream_state == "unavailable"
        assert user.status == "active"
        assert user.upstream_last_success_at is None


def test_a15_bulk_preview_uses_immutable_targets_and_rejects_changed_versions():
    with _session() as session:
        first = PortalUser(
            id="bulk-first",
            username="bulk-first",
            password_hash="hash",
            abs_username="bulk-first",
            expires_at=utcnow() + timedelta(days=5),
        )
        session.add(first)
        session.commit()
        preview = create_bulk_expiry_preview(session, extend_days=7)

        added_later = PortalUser(
            id="bulk-later",
            username="bulk-later",
            password_hash="hash",
            abs_username="bulk-later",
            expires_at=utcnow() + timedelta(days=5),
        )
        session.add(added_later)
        session.commit()

        targets = validate_bulk_expiry_preview(
            session,
            preview_token=preview["previewToken"],
            operation_id=preview["operationId"],
            extend_days=7,
        )
        assert [user.id for user in targets] == [first.id]

        first.status = "disabled"
        first.updated_at = utcnow()
        session.add(first)
        session.commit()
        with pytest.raises(BulkPreviewError, match="targets changed"):
            validate_bulk_expiry_preview(
                session,
                preview_token=preview["previewToken"],
                operation_id=preview["operationId"],
                extend_days=7,
            )


class _InactiveAbs:
    async def list_users(self):
        return [{"id": "abs-a17", "isActive": True, "mediaProgress": []}]

    async def update_user(self, user_id: str, payload: dict):
        return {"id": user_id, **payload}


@pytest.mark.anyio
async def test_a17_inactivity_enable_requires_preview_confirmation_and_delay_and_can_cancel():
    with _session() as session:
        user = PortalUser(
            id="user-a17",
            username="listener-a17",
            password_hash="hash",
            abs_user_id="abs-a17",
            abs_username="listener-a17",
            expires_at=utcnow() + timedelta(days=30),
            created_at=utcnow() - timedelta(days=90),
        )
        session.add(user)
        session.commit()
        preview = await preview_inactivity_policy(
            session,
            _InactiveAbs(),
            inactive_days=30,
            new_user_grace_days=7,
        )
        assert preview["candidateCount"] == 1
        assert get_public_settings(session)["operations"]["inactivityAutoDisable"] is False

        scheduled = confirm_inactivity_policy(
            session,
            preview_token=preview["previewToken"],
            operation_id=preview["operationId"],
            actor="root",
            delay_minutes=60,
        )
        assert scheduled.phase == "scheduled"
        assert scheduled.effective_at > utcnow()
        assert await activate_due_inactivity_policies(
            session,
            _InactiveAbs(),
            now=utcnow(),
        ) == 0
        session.refresh(user)
        assert user.status == "active"

        cancel_inactivity_policy(session, scheduled.id, actor="root")
        assert await activate_due_inactivity_policies(
            session,
            _InactiveAbs(),
            now=utcnow() + timedelta(hours=2),
        ) == 0
        assert get_public_settings(session)["operations"]["inactivityAutoDisable"] is False
