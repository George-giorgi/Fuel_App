import logging
import sqlite3
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import PROJECT_ROOT, get_database_url


DATABASE_URL = get_database_url()


def _enable_sqlite_foreign_keys(
    connection: sqlite3.Connection, _: object
) -> None:
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_database_engine(database_url: str | URL | None = None) -> Engine:
    url = (
        make_url(database_url)
        if isinstance(database_url, str)
        else database_url or get_database_url()
    )
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    connect_args: dict[str, object] = {}
    if url.get_backend_name() == "sqlite":
        if url.database and url.database != ":memory:":
            database_path = Path(url.database)
            if not database_path.is_absolute():
                database_path = PROJECT_ROOT / database_path
            database_path.parent.mkdir(parents=True, exist_ok=True)
            url = url.set(database=str(database_path))
        connect_args["check_same_thread"] = False

    engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
    if url.get_backend_name() == "sqlite":
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
