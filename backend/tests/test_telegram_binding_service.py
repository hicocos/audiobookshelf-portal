from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.config import Settings
from app.models import AuditLog, PortalUser, TelegramBindToken, utcnow
from app.security import hash_password
from app.services.telegram_binding import (
    TelegramBindingError,
    bind_telegram_user,
    create_bind_token,
    get_user_by_telegram_id,
    hash_bind_code,
    normalize_bind_code,
    unbind_telegram_user,
)


def make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def make_settings() -> Settings:
    return Settings(
        JWT_SECRET="test-secret-at-least-32-bytes-long",
        TELEGRAM_BIND_CODE_TTL_MINUTES=10,
        TELEGRAM_BIND_CODE_MAX_FAILURES=3,
    )


def seed_user(session: Session, username="alice", telegram_id=None) -> PortalUser:
    user = PortalUser(
        username=username,
        password_hash=hash_password("StrongPassword-521"),
        abs_user_id=f"abs-{username}",
        abs_username=username,
        expires_at=utcnow() + timedelta(days=5),
        telegram_id=telegram_id,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def test_create_bind_token_stores_hash_not_plain_code_and_sets_expiry():
    with make_session() as session:
        user = seed_user(session)
        settings = make_settings()

        code, token = create_bind_token(session, user, settings=settings)

        assert code.startswith("TG-")
        assert token.portal_user_id == user.id
        assert token.code_hash == hash_bind_code(code, settings=settings)
        assert code not in token.code_hash
        assert token.expires_at > utcnow()
        saved = session.exec(select(TelegramBindToken)).one()
        assert saved.id == token.id


def test_create_bind_token_rejects_already_bound_user():
    with make_session() as session:
        user = seed_user(session, telegram_id="12345")

        with pytest.raises(TelegramBindingError, match="already bound"):
            create_bind_token(session, user, settings=make_settings())


def test_bind_telegram_user_consumes_valid_code_and_writes_user_fields_and_audit_log():
    with make_session() as session:
        user = seed_user(session)
        settings = make_settings()
        code, token = create_bind_token(session, user, settings=settings)

        bound = bind_telegram_user(
            session,
            code=code.lower(),
            telegram_id="987654321",
            telegram_username="alice_tg",
            settings=settings,
        )

        assert bound.id == user.id
        assert bound.telegram_id == "987654321"
        assert bound.telegram_username == "alice_tg"
        assert bound.telegram_bound_at is not None
        saved_token = session.get(TelegramBindToken, token.id)
        assert saved_token is not None
        assert saved_token.used_at is not None
        logs = session.exec(select(AuditLog)).all()
        assert any(log.action == "telegram.bind" and log.target_id == user.id for log in logs)


def test_bind_telegram_user_rejects_expired_code_without_binding():
    with make_session() as session:
        user = seed_user(session)
        settings = make_settings()
        code, token = create_bind_token(session, user, settings=settings)
        token.expires_at = utcnow() - timedelta(seconds=1)
        session.add(token)
        session.commit()

        with pytest.raises(TelegramBindingError, match="expired"):
            bind_telegram_user(
                session,
                code=code,
                telegram_id="987654321",
                telegram_username="alice_tg",
                settings=settings,
            )

        session.refresh(user)
        assert user.telegram_id is None


def test_bind_telegram_user_rejects_used_code():
    with make_session() as session:
        user = seed_user(session)
        settings = make_settings()
        code, _token = create_bind_token(session, user, settings=settings)
        bind_telegram_user(
            session,
            code=code,
            telegram_id="987654321",
            telegram_username="alice_tg",
            settings=settings,
        )

        with pytest.raises(TelegramBindingError, match="already used"):
            bind_telegram_user(
                session,
                code=code,
                telegram_id="222222",
                telegram_username="other",
                settings=settings,
            )


def test_bind_telegram_user_rejects_same_telegram_id_bound_to_another_user():
    with make_session() as session:
        seed_user(session, username="alice", telegram_id="987654321")
        bob = seed_user(session, username="bob")
        settings = make_settings()
        code, _token = create_bind_token(session, bob, settings=settings)

        with pytest.raises(TelegramBindingError, match="telegram account already bound"):
            bind_telegram_user(
                session,
                code=code,
                telegram_id="987654321",
                telegram_username="alice_tg",
                settings=settings,
            )


def test_wrong_code_does_not_penalize_unrelated_open_tokens():
    with make_session() as session:
        user = seed_user(session)
        settings = make_settings()
        _code, token = create_bind_token(session, user, settings=settings)

        for _ in range(3):
            with pytest.raises(TelegramBindingError, match="not found"):
                bind_telegram_user(
                    session,
                    code="TG-WRONG-0000",
                    telegram_id="987654321",
                    telegram_username="alice_tg",
                    settings=settings,
                )

        saved = session.get(TelegramBindToken, token.id)
        assert saved is not None
        assert saved.failed_attempts == 0


def test_create_bind_token_revokes_previous_unused_tokens_for_same_user():
    with make_session() as session:
        user = seed_user(session)
        settings = make_settings()
        first_code, first = create_bind_token(session, user, settings=settings)
        second_code, second = create_bind_token(session, user, settings=settings)

        assert first_code != second_code
        saved_first = session.get(TelegramBindToken, first.id)
        assert saved_first is not None
        assert saved_first.used_at is not None
        with pytest.raises(TelegramBindingError, match="already used"):
            bind_telegram_user(
                session,
                code=first_code,
                telegram_id="987654321",
                telegram_username="alice_tg",
                settings=settings,
            )
        assert session.get(TelegramBindToken, second.id).used_at is None


def test_unbind_telegram_user_clears_fields_and_writes_audit_log():
    with make_session() as session:
        user = seed_user(session, telegram_id="987654321")
        user.telegram_username = "alice_tg"
        user.telegram_bound_at = utcnow()
        session.add(user)
        session.commit()

        updated = unbind_telegram_user(session, user)

        assert updated.telegram_id is None
        assert updated.telegram_username is None
        assert updated.telegram_bound_at is None
        logs = session.exec(select(AuditLog)).all()
        assert any(log.action == "telegram.unbind" and log.target_id == user.id for log in logs)


def test_get_user_by_telegram_id_returns_bound_user():
    with make_session() as session:
        user = seed_user(session, telegram_id="987654321")

        assert get_user_by_telegram_id(session, "987654321").id == user.id
        assert get_user_by_telegram_id(session, "missing") is None
