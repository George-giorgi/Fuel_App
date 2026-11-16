import logging
import sqlite3
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import URL, create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import DATA_DIRECTORY, DATABASE_PATH


DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
DATABASE_URL = URL.create("sqlite", database=str(DATABASE_PATH))


def _enable_sqlite_foreign_keys(
    connection: sqlite3.Connection, _: object
) -> None:
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_database_engine(database_url: str | URL = DATABASE_URL) -> Engine:
    url = make_url(database_url) if isinstance(database_url, str) else database_url
    if url.get_backend_name() != "sqlite":
        raise ValueError("The local Diesel Desk database must use SQLite.")

    engine = create_engine(url, connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


engine = create_database_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

logger = logging.getLogger(__name__)


@event.listens_for(Session, "after_commit")
def _clear_pending_uploads(session: Session) -> None:
    session.info.pop("rollback_upload_paths", None)


@event.listens_for(Session, "after_rollback")
def _remove_pending_uploads(session: Session) -> None:
    paths = session.info.pop("rollback_upload_paths", [])
    for path in paths:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not remove an uncommitted meter photo.")


def get_db_session() -> Generator[Session, None, None]:
    with SessionLocal.begin() as session:
        yield session
