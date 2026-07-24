from datetime import timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models import Code, PortalUser, utcnow
from app.services.codes import CodeValidationError, generate_code, redeem_code


def make_session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_generate_code_creates_uppercase_code_with_defaults():
    with make_session() as session:
        code = generate_code(session, type="register", duration_days=30, created_by="admin")

        assert code.type == "register"
        assert code.duration_days == 30
        assert code.max_uses == 1
        assert code.status == "active"
        assert len(code.code) >= 10
        assert code.code == code.code.upper()


def test_redeem_code_increments_usage_and_returns_duration():
    with make_session() as session:
        code = Code(code="ABCD-EFGH", type="register", duration_days=14)
        session.add(code)
        session.commit()

        redeemed = redeem_code(session, "ABCD-EFGH", username="alice", action="register")

        assert redeemed.duration_days == 14
        assert redeemed.used_count == 1


def test_redeem_code_rejects_reuse_when_max_uses_reached():
    with make_session() as session:
        session.add(Code(code="USED-CODE", type="register", max_uses=1, used_count=1))
        session.commit()

        with pytest.raises(CodeValidationError, match="already used"):
            redeem_code(session, "USED-CODE", username="alice", action="register")


def test_redeem_code_rejects_expired_and_designated_mismatch():
    with make_session() as session:
        session.add(
            Code(
                code="ONLY-BOB",
                type="register",
                designated_username="bob",
                expires_at=utcnow() + timedelta(days=1),
            )
        )
        session.add(
            Code(
                code="EXPIRED",
                type="register",
                expires_at=utcnow() - timedelta(seconds=1),
            )
        )
        session.commit()

        with pytest.raises(CodeValidationError, match="designated"):
            redeem_code(session, "ONLY-BOB", username="alice", action="register")
        with pytest.raises(CodeValidationError, match="expired"):
            redeem_code(session, "EXPIRED", username="alice", action="register")


def test_a10_multi_user_renewal_code_defaults_to_one_use_per_user():
    with make_session() as session:
        alice = PortalUser(
            id="alice-id",
            username="alice",
            password_hash="hash",
            abs_username="alice",
        )
        bob = PortalUser(
            id="bob-id",
            username="bob",
            password_hash="hash",
            abs_username="bob",
        )
        code = Code(
            code="TEAM-RENEW-01",
            type="renew",
            duration_days=30,
            max_uses=5,
        )
        session.add(alice)
        session.add(bob)
        session.add(code)
        session.commit()

        redeem_code(
            session,
            code.code,
            username=alice.username,
            action="renew",
            portal_user_id=alice.id,
            operation_id="renew-alice-1",
        )
        with pytest.raises(CodeValidationError, match="already used by this user"):
            redeem_code(
                session,
                code.code,
                username=alice.username,
                action="renew",
                portal_user_id=alice.id,
                operation_id="renew-alice-2",
            )
        redeem_code(
            session,
            code.code,
            username=bob.username,
            action="renew",
            portal_user_id=bob.id,
            operation_id="renew-bob-1",
        )

        session.refresh(code)
        assert code.per_user_max_uses == 1
        assert code.used_count == 2
