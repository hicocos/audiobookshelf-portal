from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import Session

from app.db import create_db_and_tables, create_db_engine
from app.models import PortalUser


def test_concurrent_case_variant_registration_has_one_winner_without_lock_error(tmp_path: Path):
    engine = create_db_engine(f"sqlite:///{tmp_path / 'concurrent.db'}")
    create_db_and_tables(engine)
    barrier = Barrier(2)
    result_lock = Lock()
    results: list[str] = []

    def insert(username: str, suffix: str) -> None:
        try:
            barrier.wait(timeout=5)
            with Session(engine) as session:
                session.add(
                    PortalUser(
                        username=username,
                        password_hash="hash",
                        abs_user_id=f"abs-{suffix}",
                        abs_username=f"abs-{suffix}",
                    )
                )
                session.commit()
        except IntegrityError:
            outcome = "conflict"
        except OperationalError as exc:
            outcome = f"lock:{exc}"
        else:
            outcome = "created"
        with result_lock:
            results.append(outcome)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda args: insert(*args), [("Alice", "one"), ("alice", "two")]))

    assert sorted(results) == ["conflict", "created"]
    assert not any(item.startswith("lock:") for item in results)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM portal_users")).scalar_one() == 1
