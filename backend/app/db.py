from collections.abc import Generator
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from app.config import Settings
from app.db_migrations import run_migrations


def _ensure_sqlite_parent(url: str) -> None:
    if not url.startswith("sqlite") or url in {"sqlite://", "sqlite:///:memory:"}:
        return
    parsed = urlparse(url)
    if parsed.path and parsed.path != "/:memory:":
        Path(parsed.path).parent.mkdir(parents=True, exist_ok=True)


def create_db_engine(database_url: str | None = None):
    settings = Settings()
    url = database_url or settings.database_url
    _ensure_sqlite_parent(url)
    connect_args = {
        "check_same_thread": False,
        "timeout": 10,
    } if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
    if url.startswith("sqlite"):
        _configure_sqlite(engine)
    return engine


def _configure_sqlite(engine: Engine) -> None:
    """Apply SQLite safety/concurrency PRAGMAs to every pooled connection."""

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()


@lru_cache(maxsize=None)
def get_engine(database_url: str | None = None) -> Engine:
    """Return one Engine per database URL for the lifetime of this process."""

    url = database_url or Settings().database_url
    return create_db_engine(url)


def create_db_and_tables(engine) -> None:
    SQLModel.metadata.create_all(engine)
    run_migrations(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session
