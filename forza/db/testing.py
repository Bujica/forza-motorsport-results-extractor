from __future__ import annotations

from sqlalchemy.engine import Engine

from .session import create_db_and_tables


def create_test_db_and_tables(engine: Engine) -> None:
    """Create SQLModel tables for isolated tests.

    Runtime databases must use Alembic migrations. This helper exists only for
    tests that intentionally exercise repository behavior without a migration
    setup step.
    """

    create_db_and_tables(engine)
