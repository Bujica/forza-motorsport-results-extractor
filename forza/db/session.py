from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool
from sqlmodel import Session, SQLModel, create_engine


def create_sqlite_engine(
    path: Path | str,
    *,
    echo: bool = False,
    apply_runtime_pragmas: bool = True,
) -> Engine:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=echo,
        poolclass=NullPool,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    if apply_runtime_pragmas:
        _install_sqlite_pragmas(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            connection.exec_driver_sql("PRAGMA synchronous=NORMAL")
    return engine


def _install_sqlite_pragmas(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
        finally:
            cursor.close()


def create_db_and_tables(engine: Engine) -> None:
    """Create all tables via SQLModel metadata.

    For PRODUCTION use: call ``forza.db.migrate.upgrade_database()`` instead.
    This function is reserved for:
      - test fixtures that need an isolated in-memory or temp database

    Never call this from application services in normal operation.
    """
    SQLModel.metadata.create_all(engine)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
