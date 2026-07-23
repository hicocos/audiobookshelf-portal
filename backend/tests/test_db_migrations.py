import pytest
from sqlalchemy import text
from sqlmodel import create_engine
from sqlalchemy.pool import StaticPool

from app.db_migrations import run_migrations


def _legacy_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE portal_users (
                id VARCHAR PRIMARY KEY,
                username VARCHAR NOT NULL,
                password_hash VARCHAR NOT NULL,
                email VARCHAR,
                telegram_id VARCHAR,
                role VARCHAR NOT NULL DEFAULT 'user',
                status VARCHAR NOT NULL DEFAULT 'active',
                abs_user_id VARCHAR,
                abs_username VARCHAR NOT NULL,
                expires_at DATETIME,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                last_login_at DATETIME
            )
            """
        )
    return engine


def _columns(engine, table_name: str) -> set[str]:
    with engine.connect() as conn:
        return {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table_name})")}


def _indexes(engine, table_name: str) -> set[str]:
    with engine.connect() as conn:
        return {row[1] for row in conn.exec_driver_sql(f"PRAGMA index_list({table_name})")}


def test_migrations_add_telegram_columns_table_and_unique_index_to_legacy_database():
    engine = _legacy_engine()

    run_migrations(engine)

    portal_columns = _columns(engine, "portal_users")
    assert "telegram_username" in portal_columns
    assert "telegram_bound_at" in portal_columns
    assert "telegram_binding_required" in portal_columns

    token_columns = _columns(engine, "telegram_bind_tokens")
    assert {
        "id",
        "portal_user_id",
        "code_hash",
        "expires_at",
        "used_at",
        "failed_attempts",
        "created_at",
    }.issubset(token_columns)

    assert "ux_portal_users_telegram_id" in _indexes(engine, "portal_users")
    assert "ux_telegram_bind_tokens_code_hash" in _indexes(engine, "telegram_bind_tokens")
    assert "ux_telegram_flow_sessions_telegram_id" in _indexes(engine, "telegram_flow_sessions")
    assert "ux_password_reset_tokens_token_hash" in _indexes(engine, "password_reset_tokens")
    assert "ux_telegram_notifications_dedupe_key" in _indexes(engine, "telegram_notifications")
    assert "ix_telegram_notifications_delivery" in _indexes(engine, "telegram_notifications")
    assert "ux_tg_group_memberships_user" in _indexes(
        engine, "telegram_group_memberships"
    )
    assert "ix_tg_group_memberships_due" in _indexes(
        engine, "telegram_group_memberships"
    )
    assert "ix_media_requests_status" in _indexes(engine, "media_requests")
    assert "ix_point_accounts_leaderboard" in _indexes(engine, "point_accounts")
    assert "ux_point_ledger_reference" in _indexes(engine, "point_ledger_entries")
    assert "ux_daily_checkins_user_date" in _indexes(engine, "daily_checkins")
    assert "ux_referral_invites_code" in _indexes(engine, "referral_invites")


def test_migrations_are_idempotent():
    engine = _legacy_engine()

    run_migrations(engine)
    run_migrations(engine)

    assert "telegram_username" in _columns(engine, "portal_users")
    assert "telegram_bound_at" in _columns(engine, "portal_users")
    assert "telegram_binding_required" in _columns(engine, "portal_users")


def test_migration_grandfathers_existing_accounts_out_of_required_binding():
    engine = _legacy_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO portal_users
                (id, username, password_hash, role, status, abs_username, created_at, updated_at)
                VALUES
                ('legacy', 'legacy_user', 'hash', 'user', 'active', 'legacy_user', '2026-01-01', '2026-01-01')
                """
            )
        )

    run_migrations(engine)

    with engine.connect() as conn:
        required = conn.execute(
            text("SELECT telegram_binding_required FROM portal_users WHERE id = 'legacy'")
        ).scalar_one()
    assert required == 0


def test_telegram_id_unique_index_allows_multiple_nulls_but_rejects_duplicate_values():
    engine = _legacy_engine()
    run_migrations(engine)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO portal_users
                (id, username, password_hash, telegram_id, role, status, abs_username, created_at, updated_at)
                VALUES
                ('u1', 'alice', 'hash', NULL, 'user', 'active', 'alice', '2026-01-01', '2026-01-01'),
                ('u2', 'bob', 'hash', NULL, 'user', 'active', 'bob', '2026-01-01', '2026-01-01')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO portal_users
                (id, username, password_hash, telegram_id, role, status, abs_username, created_at, updated_at)
                VALUES
                ('u3', 'charlie', 'hash', '12345', 'user', 'active', 'charlie', '2026-01-01', '2026-01-01')
                """
            )
        )
        with pytest.raises(Exception):
            conn.execute(
                text(
                    """
                    INSERT INTO portal_users
                    (id, username, password_hash, telegram_id, role, status, abs_username, created_at, updated_at)
                    VALUES
                    ('u4', 'dave', 'hash', '12345', 'user', 'active', 'dave', '2026-01-01', '2026-01-01')
                    """
                )
            )
