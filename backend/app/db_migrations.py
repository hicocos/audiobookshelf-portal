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
            if "session_version" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE portal_users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0"
                    )
                )
            if "password_changed_at" not in columns:
                conn.execute(text("ALTER TABLE portal_users ADD COLUMN password_changed_at DATETIME"))
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
