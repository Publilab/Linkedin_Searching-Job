from __future__ import annotations

import sqlite3
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import settings


def _resolve_database_url() -> str:
    configured = (settings.database_url or "").strip()
    if settings.seekjob_data_dir and configured in {"", "sqlite:///./app.db"}:
        data_dir = Path(settings.seekjob_data_dir).expanduser()
        data_dir.mkdir(parents=True, exist_ok=True)
        db_path = (data_dir / "app.db").resolve()
        return f"sqlite:///{db_path}"

    return configured or "sqlite:///./app.db"


database_url = _resolve_database_url()
is_sqlite = database_url.startswith("sqlite")
connect_args = {"check_same_thread": False, "timeout": 30} if is_sqlite else {}
engine = create_engine(database_url, future=True, connect_args=connect_args)


def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA busy_timeout=30000;")
        cursor.execute("PRAGMA foreign_keys=ON;")

        # Best effort: do not fail request startup if another process currently owns a write lock.
        try:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
        except sqlite3.OperationalError:
            pass
    finally:
        cursor.close()


if is_sqlite:
    event.listen(engine, "connect", _set_sqlite_pragmas)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
