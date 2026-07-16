from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.db import create_db_and_tables, create_db_engine, get_engine
from app.models import PortalUser


def test_get_engine_is_process_singleton_for_same_database_url(tmp_path: Path):
    database_url = f"sqlite:///{tmp_path / 'portal.db'}"

    first = get_engine(database_url)
    second = get_engine(database_url)

    assert first is second


def test_every_sqlite_connection_enables_wal_foreign_keys_and_busy_timeout(tmp_path: Path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'portal.db'}")
    create_db_and_tables(engine)

    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode")).scalar_one().lower() == "wal"
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        assert connection.execute(text("PRAGMA busy_timeout")).scalar_one() >= 5000


def test_normalized_username_columns_enforce_case_insensitive_uniqueness(tmp_path: Path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'portal.db'}")
    create_db_and_tables(engine)

    with Session(engine) as session:
        session.add(
            PortalUser(
                username="Alice",
                password_hash="hash",
                abs_user_id="abs-1",
                abs_username="Alice",
            )
        )
        session.commit()

        session.add(
            PortalUser(
                username="alice",
                password_hash="hash",
                abs_user_id="abs-2",
                abs_username="alice-2",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_normalized_fields_follow_username_mutations(tmp_path: Path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'portal.db'}")
    create_db_and_tables(engine)

    with Session(engine) as session:
        user = PortalUser(
            username="Original",
            password_hash="hash",
            abs_user_id="abs-1",
            abs_username="OriginalAbs",
        )
        session.add(user)
        session.commit()
        user.username = "Renamed"
        user.abs_username = "RenamedAbs"
        session.add(user)
        session.commit()
        session.refresh(user)

        assert user.username_normalized == "renamed"
        assert user.abs_username_normalized == "renamedabs"


def test_normalized_abs_username_columns_enforce_case_insensitive_uniqueness(tmp_path: Path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'portal.db'}")
    create_db_and_tables(engine)

    with Session(engine) as session:
        session.add(
            PortalUser(
                username="first",
                password_hash="hash",
                abs_user_id="abs-1",
                abs_username="SharedName",
            )
        )
        session.commit()

        session.add(
            PortalUser(
                username="second",
                password_hash="hash",
                abs_user_id="abs-2",
                abs_username="sharedname",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
