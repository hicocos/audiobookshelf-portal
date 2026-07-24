from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.models import normalize_username


def _sqlite_table_columns(connection, table_name: str) -> set[str]:
    return {
        row[1]
        for row in connection.exec_driver_sql(f"PRAGMA table_info({table_name})")
    }


def _table_exists(connection, table_name: str) -> bool:
    return connection.exec_driver_sql(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).first() is not None


def run_migrations(engine: Engine) -> None:
    """Run small idempotent migrations for existing SQLite deployments.

    SQLModel.metadata.create_all creates new tables but does not alter existing
    tables. The production portal already has a SQLite database, so new columns
    and indexes must be added explicitly and safely on startup.
    """
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as conn:
        if _table_exists(conn, "portal_users"):
            columns = _sqlite_table_columns(conn, "portal_users")
            if "telegram_username" not in columns:
                conn.execute(text("ALTER TABLE portal_users ADD COLUMN telegram_username VARCHAR"))
            if "telegram_bound_at" not in columns:
                conn.execute(text("ALTER TABLE portal_users ADD COLUMN telegram_bound_at DATETIME"))
            if "telegram_binding_required" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE portal_users ADD COLUMN telegram_binding_required "
                        "BOOLEAN NOT NULL DEFAULT 0"
                    )
                )
            if "session_version" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE portal_users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0"
                    )
                )
            if "password_changed_at" not in columns:
                conn.execute(text("ALTER TABLE portal_users ADD COLUMN password_changed_at DATETIME"))
            if "upstream_state" not in columns:
                conn.execute(text("ALTER TABLE portal_users ADD COLUMN upstream_state VARCHAR NOT NULL DEFAULT 'pending'"))
            if "upstream_last_success_at" not in columns:
                conn.execute(text("ALTER TABLE portal_users ADD COLUMN upstream_last_success_at DATETIME"))
            if "username_normalized" not in columns:
                conn.execute(text("ALTER TABLE portal_users ADD COLUMN username_normalized VARCHAR"))
            if "abs_username_normalized" not in columns:
                conn.execute(text("ALTER TABLE portal_users ADD COLUMN abs_username_normalized VARCHAR"))

            users = conn.execute(
                text("SELECT id, username, abs_username FROM portal_users")
            ).mappings().all()
            normalized_usernames: dict[str, str] = {}
            normalized_abs_usernames: dict[str, str] = {}
            for user in users:
                username_normalized = normalize_username(str(user["username"]))
                abs_username_normalized = normalize_username(str(user["abs_username"]))
                if username_normalized in normalized_usernames:
                    raise RuntimeError(
                        "Cannot enforce case-insensitive username uniqueness: "
                        f"portal_users {normalized_usernames[username_normalized]} and {user['id']} collide"
                    )
                if abs_username_normalized in normalized_abs_usernames:
                    raise RuntimeError(
                        "Cannot enforce case-insensitive ABS username uniqueness: "
                        f"portal_users {normalized_abs_usernames[abs_username_normalized]} and {user['id']} collide"
                    )
                normalized_usernames[username_normalized] = str(user["id"])
                normalized_abs_usernames[abs_username_normalized] = str(user["id"])
                conn.execute(
                    text(
                        "UPDATE portal_users "
                        "SET username_normalized = :username_normalized, "
                        "abs_username_normalized = :abs_username_normalized "
                        "WHERE id = :id"
                    ),
                    {
                        "id": user["id"],
                        "username_normalized": username_normalized,
                        "abs_username_normalized": abs_username_normalized,
                    },
                )

            conn.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS ux_portal_users_username_normalized
                    ON portal_users(username_normalized)
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS ux_portal_users_abs_username_normalized
                    ON portal_users(abs_username_normalized)
                    """
                )
            )

            conn.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS ux_portal_users_telegram_id
                    ON portal_users(telegram_id)
                    WHERE telegram_id IS NOT NULL AND telegram_id != ''
                    """
                )
            )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS telegram_bind_tokens (
                    id VARCHAR PRIMARY KEY,
                    portal_user_id VARCHAR NOT NULL REFERENCES portal_users(id) ON DELETE CASCADE,
                    code_hash VARCHAR NOT NULL,
                    expires_at DATETIME NOT NULL,
                    used_at DATETIME,
                    failed_attempts INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_telegram_bind_tokens_portal_user_id
                ON telegram_bind_tokens(portal_user_id)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS ux_telegram_bind_tokens_code_hash
                ON telegram_bind_tokens(code_hash)
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS telegram_flow_sessions (
                    id VARCHAR PRIMARY KEY,
                    telegram_id VARCHAR NOT NULL,
                    kind VARCHAR NOT NULL,
                    step VARCHAR NOT NULL,
                    payload_json VARCHAR NOT NULL DEFAULT '{}',
                    expires_at DATETIME NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_telegram_flow_sessions_telegram_id ON telegram_flow_sessions(telegram_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_flow_sessions_kind ON telegram_flow_sessions(kind)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_flow_sessions_step ON telegram_flow_sessions(step)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_flow_sessions_expires_at ON telegram_flow_sessions(expires_at)"))

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    id VARCHAR PRIMARY KEY,
                    portal_user_id VARCHAR NOT NULL REFERENCES portal_users(id) ON DELETE CASCADE,
                    token_hash VARCHAR NOT NULL,
                    expires_at DATETIME NOT NULL,
                    used_at DATETIME,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_password_reset_tokens_token_hash ON password_reset_tokens(token_hash)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_password_reset_tokens_portal_user_id ON password_reset_tokens(portal_user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_password_reset_tokens_expires_at ON password_reset_tokens(expires_at)"))

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS telegram_notifications (
                    id VARCHAR PRIMARY KEY,
                    dedupe_key VARCHAR NOT NULL,
                    telegram_id VARCHAR NOT NULL,
                    kind VARCHAR NOT NULL,
                    message VARCHAR NOT NULL,
                    status VARCHAR NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at DATETIME NOT NULL,
                    claimed_at DATETIME,
                    sent_at DATETIME,
                    last_error VARCHAR,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_telegram_notifications_dedupe_key ON telegram_notifications(dedupe_key)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_notifications_telegram_id ON telegram_notifications(telegram_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_notifications_kind ON telegram_notifications(kind)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_notifications_status ON telegram_notifications(status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_notifications_next_attempt_at ON telegram_notifications(next_attempt_at)"))
        notification_columns = _sqlite_table_columns(conn, "telegram_notifications")
        if "version" not in notification_columns:
            conn.execute(text("ALTER TABLE telegram_notifications ADD COLUMN version INTEGER NOT NULL DEFAULT 0"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_notifications_delivery ON telegram_notifications(status, next_attempt_at)"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS telegram_group_memberships (
                id VARCHAR PRIMARY KEY,
                portal_user_id VARCHAR NOT NULL REFERENCES portal_users(id) ON DELETE CASCADE,
                telegram_id VARCHAR NOT NULL,
                group_id VARCHAR NOT NULL,
                status VARCHAR NOT NULL DEFAULT 'member',
                left_at DATETIME,
                grace_expires_at DATETIME,
                last_checked_at DATETIME NOT NULL,
                disabled_at DATETIME,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_tg_group_memberships_user ON telegram_group_memberships(portal_user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tg_group_memberships_due ON telegram_group_memberships(status, grace_expires_at)"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS media_requests (
                id VARCHAR PRIMARY KEY,
                portal_user_id VARCHAR NOT NULL REFERENCES portal_users(id) ON DELETE CASCADE,
                kind VARCHAR NOT NULL,
                title VARCHAR NOT NULL,
                details VARCHAR,
                status VARCHAR NOT NULL DEFAULT 'pending',
                admin_note VARCHAR,
                handled_by_user_id VARCHAR REFERENCES portal_users(id) ON DELETE SET NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                resolved_at DATETIME
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_media_requests_user ON media_requests(portal_user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_media_requests_status ON media_requests(status)"))
        media_request_columns = _sqlite_table_columns(conn, "media_requests")
        if "open_slot" not in media_request_columns:
            conn.execute(text("ALTER TABLE media_requests ADD COLUMN open_slot INTEGER"))
        overflow = conn.execute(
            text(
                "SELECT portal_user_id, COUNT(*) AS count FROM media_requests "
                "WHERE status IN ('pending', 'accepted') "
                "GROUP BY portal_user_id HAVING COUNT(*) > 3"
            )
        ).first()
        if overflow is not None:
            raise RuntimeError(
                "Cannot enforce media request limit: a user has more than 3 open requests"
            )
        open_requests = conn.execute(
            text(
                "SELECT id, portal_user_id FROM media_requests "
                "WHERE status IN ('pending', 'accepted') "
                "ORDER BY portal_user_id, created_at, id"
            )
        ).mappings().all()
        next_slot: dict[str, int] = {}
        for request in open_requests:
            user_id = str(request["portal_user_id"])
            slot = next_slot.get(user_id, 1)
            conn.execute(
                text("UPDATE media_requests SET open_slot = :slot WHERE id = :id"),
                {"slot": slot, "id": request["id"]},
            )
            next_slot[user_id] = slot + 1
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_media_requests_user_open_slot "
                "ON media_requests(portal_user_id, open_slot) "
                "WHERE open_slot IS NOT NULL"
            )
        )

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS point_accounts (
                portal_user_id VARCHAR PRIMARY KEY REFERENCES portal_users(id) ON DELETE CASCADE,
                balance INTEGER NOT NULL DEFAULT 0,
                lifetime_earned INTEGER NOT NULL DEFAULT 0,
                leaderboard_opt_in BOOLEAN NOT NULL DEFAULT 0,
                updated_at DATETIME NOT NULL
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_point_accounts_leaderboard ON point_accounts(leaderboard_opt_in, lifetime_earned)"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS point_ledger_entries (
                id VARCHAR PRIMARY KEY,
                portal_user_id VARCHAR NOT NULL REFERENCES portal_users(id) ON DELETE CASCADE,
                amount INTEGER NOT NULL,
                balance_after INTEGER NOT NULL,
                kind VARCHAR NOT NULL,
                reference VARCHAR NOT NULL,
                detail_json VARCHAR,
                created_at DATETIME NOT NULL
            )
        """))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_point_ledger_reference ON point_ledger_entries(reference)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_point_ledger_user_created ON point_ledger_entries(portal_user_id, created_at)"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS daily_checkins (
                id VARCHAR PRIMARY KEY,
                portal_user_id VARCHAR NOT NULL REFERENCES portal_users(id) ON DELETE CASCADE,
                local_date VARCHAR NOT NULL,
                streak INTEGER NOT NULL,
                points_awarded INTEGER NOT NULL,
                ledger_entry_id VARCHAR NOT NULL REFERENCES point_ledger_entries(id) ON DELETE RESTRICT,
                created_at DATETIME NOT NULL
            )
        """))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_daily_checkins_user_date ON daily_checkins(portal_user_id, local_date)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_daily_checkins_ledger ON daily_checkins(ledger_entry_id)"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS referral_invites (
                id VARCHAR PRIMARY KEY,
                inviter_user_id VARCHAR NOT NULL REFERENCES portal_users(id) ON DELETE CASCADE,
                code_id VARCHAR NOT NULL REFERENCES codes(id) ON DELETE CASCADE,
                used_by_user_id VARCHAR REFERENCES portal_users(id) ON DELETE SET NULL,
                reward_points INTEGER NOT NULL,
                expires_at DATETIME NOT NULL,
                settled_at DATETIME,
                created_at DATETIME NOT NULL
            )
        """))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_referral_invites_code ON referral_invites(code_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_referral_invites_inviter_created ON referral_invites(inviter_user_id, created_at)"))

        if _table_exists(conn, "codes"):
            code_columns = _sqlite_table_columns(conn, "codes")
            if "per_user_max_uses" not in code_columns:
                conn.execute(text("ALTER TABLE codes ADD COLUMN per_user_max_uses INTEGER NOT NULL DEFAULT 1"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS account_holds (
                id VARCHAR PRIMARY KEY,
                portal_user_id VARCHAR NOT NULL REFERENCES portal_users(id) ON DELETE CASCADE,
                kind VARCHAR NOT NULL,
                active BOOLEAN NOT NULL DEFAULT 1,
                actor VARCHAR,
                source VARCHAR,
                metadata_json VARCHAR,
                started_at DATETIME NOT NULL,
                cleared_at DATETIME,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_account_holds_user_kind ON account_holds(portal_user_id, kind)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_account_holds_active ON account_holds(active)"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS account_operations (
                id VARCHAR PRIMARY KEY,
                kind VARCHAR NOT NULL,
                portal_user_id VARCHAR REFERENCES portal_users(id) ON DELETE SET NULL,
                idempotency_key VARCHAR NOT NULL,
                phase VARCHAR NOT NULL,
                status VARCHAR NOT NULL DEFAULT 'pending',
                request_hash VARCHAR,
                result_json VARCHAR,
                last_error VARCHAR,
                reconciliation_job_id VARCHAR REFERENCES reconciliation_jobs(id) ON DELETE SET NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                effective_at DATETIME,
                completed_at DATETIME
            )
        """))
        operation_columns = _sqlite_table_columns(conn, "account_operations")
        if "effective_at" not in operation_columns:
            conn.execute(text("ALTER TABLE account_operations ADD COLUMN effective_at DATETIME"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_account_operations_idempotency ON account_operations(idempotency_key)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_account_operations_kind_status ON account_operations(kind, status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_account_operations_effective ON account_operations(effective_at)"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS operation_previews (
                id VARCHAR PRIMARY KEY,
                kind VARCHAR NOT NULL,
                portal_user_id VARCHAR REFERENCES portal_users(id) ON DELETE CASCADE,
                operation_id VARCHAR NOT NULL,
                payload_json VARCHAR NOT NULL,
                snapshot_hash VARCHAR NOT NULL,
                expires_at DATETIME NOT NULL,
                consumed_at DATETIME,
                created_at DATETIME NOT NULL
            )
        """))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_operation_previews_operation ON operation_previews(operation_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_operation_previews_expires ON operation_previews(expires_at)"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id VARCHAR PRIMARY KEY,
                actor_user_id VARCHAR,
                actor_username VARCHAR,
                action VARCHAR NOT NULL,
                target_type VARCHAR,
                target_id VARCHAR,
                detail_json VARCHAR,
                ip_address VARCHAR,
                created_at DATETIME NOT NULL
            )
        """))
        audit_columns = _sqlite_table_columns(conn, "audit_logs")
        for column in ("actor_user_id", "actor_username", "target_type", "target_id", "detail_json", "ip_address"):
            if column not in audit_columns:
                conn.execute(text(f"ALTER TABLE audit_logs ADD COLUMN {column} VARCHAR"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_audit_logs_action_created ON audit_logs(action, created_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_audit_logs_actor_created ON audit_logs(actor_username, created_at)"))
