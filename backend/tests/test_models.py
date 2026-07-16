from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlmodel import Session, SQLModel, create_engine, select

from app.models import AuditLog, Code, CodeRedemption, PortalUser, utcnow


def test_models_create_expected_tables_and_rows():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        user = PortalUser(
            username="alice",
            password_hash="hash",
            abs_user_id="abs-1",
            abs_username="alice",
            expires_at=utcnow() + timedelta(days=30),
        )
        code = Code(code="ABCD-EFGH", type="register", duration_days=30)
        session.add(user)
        session.add(code)
        session.commit()

        saved_user = session.exec(select(PortalUser).where(PortalUser.username == "alice")).one()
        saved_code = session.exec(select(Code).where(Code.code == "ABCD-EFGH")).one()

        assert UUID(saved_user.id)
        assert saved_user.role == "user"
        assert saved_user.status == "active"
        assert saved_code.status == "active"
        assert saved_code.max_uses == 1
        assert saved_code.used_count == 0


def test_redemption_and_audit_log_defaults_are_utc():
    redemption = CodeRedemption(
        code_id="code-id",
        portal_user_id="user-id",
        username_snapshot="alice",
        action="register",
    )
    log = AuditLog(action="register", target_type="user", target_id="user-id")

    assert redemption.created_at.tzinfo == UTC
    assert log.created_at.tzinfo == UTC
    assert datetime.now(UTC) >= redemption.created_at
