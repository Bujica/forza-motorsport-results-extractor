"""Alembic runtime integration for forza.

All production database creation and migration goes through this module.
``forza.db.testing.create_test_db_and_tables()`` is the explicit helper for
tests that need SQLModel ``create_all`` without Alembic.

Public API
----------
upgrade_database(database_file)
    Apply all pending migrations. Safe to call repeatedly (idempotent).

ensure_db_ready(database_file)
    Explicit helper for controlled setup/import paths.

require_db_ready(database_file)
    Non-mutating runtime gate. Raises unless the database is at head.

detect_database_state(database_file) -> DatabaseSchemaState
    Non-destructive diagnostic — never modifies the database.

current_revision(database_file) -> str | None
    Return the current Alembic revision, or None if uninitialized.

is_up_to_date(database_file) -> bool
    True if the database is at the latest migration head.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
import sqlite3

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

# Absolute path to the migrations directory — works regardless of CWD.
_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class DatabaseSchemaState(str, Enum):
    MISSING   = "missing"    # DB file does not exist
    EMPTY     = "empty"      # DB file exists but has no tables
    UNMANAGED = "unmanaged"  # Has tables but no alembic_version — not safe to migrate
    OUTDATED  = "outdated"   # Managed but behind head revision
    CURRENT   = "current"    # Managed and at head revision
    ERROR     = "error"      # Could not determine state


def _make_config(database_url: str) -> Config:
    """Build an Alembic Config with script_location and URL set programmatically."""
    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def _db_url(database_file: Path) -> str:
    return f"sqlite:///{database_file}"


def detect_database_state(database_file: Path) -> DatabaseSchemaState:
    """Non-destructive inspection of the database state.

    Never creates files, tables, or applies migrations.
    """
    if not database_file.exists():
        return DatabaseSchemaState.MISSING

    url = _db_url(database_file)
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
    except Exception:
        return DatabaseSchemaState.ERROR
    finally:
        engine.dispose()

    if not tables:
        return DatabaseSchemaState.EMPTY

    # Check for alembic_version table — presence means Alembic manages this DB.
    if "alembic_version" not in tables:
        return DatabaseSchemaState.UNMANAGED

    # DB is managed — check whether it's current.
    try:
        rev = current_revision(database_file)
        cfg = _make_config(url)
        scripts = ScriptDirectory.from_config(cfg)
        head = scripts.get_current_head()
        if rev == head:
            if not _matches_current_schema_shape(database_file):
                return DatabaseSchemaState.UNMANAGED
            return DatabaseSchemaState.CURRENT

        # Clean-break policy: a database stamped with a revision that is not
        # present in the current baseline is outside the supported migration
        # chain. Treat it as unmanaged and require an explicit db-reset or
        # manual backup/removal under the clean-break baseline policy.
        if rev is not None:
            try:
                scripts.get_revision(rev)
            except Exception:
                return DatabaseSchemaState.UNMANAGED

        return DatabaseSchemaState.OUTDATED
    except Exception:
        return DatabaseSchemaState.ERROR


def _matches_current_schema_shape(database_file: Path) -> bool:
    """Reject managed DBs stamped as head but built from an older clean break."""
    required_columns = {
        "image_files": {"duplicate_of_image_file_id"},
        "run_inputs": {"image_file_id"},
        "extraction_results": {"image_file_id"},
        "extraction_attempts": {"image_file_id"},
        "model_artifacts": {"image_file_id"},
        "lap_records": {"image_file_id"},
        "review_cases": {"image_file_id"},
        "review_corrections": {"image_file_id"},
        "image_flags": {"image_file_id"},
    }
    try:
        with sqlite3.connect(database_file) as connection:
            for table_name, required in required_columns.items():
                columns = {
                    str(row[1])
                    for row in connection.execute(f'PRAGMA table_info("{table_name}")')
                }
                if not required.issubset(columns):
                    return False
    except sqlite3.Error:
        return False
    return True


def upgrade_database(database_file: Path) -> None:
    """Apply all pending Alembic migrations.

    Creates the database file and parent directory if they do not exist.
    Safe to call multiple times — idempotent.

    Raises
    ------
    RuntimeError
        If the database exists but was not created by Alembic (no
        ``alembic_version`` table). Call
        ``maintenance db-reset --yes`` or remove the database file first.
    """
    state = detect_database_state(database_file)

    if state == DatabaseSchemaState.UNMANAGED:
        raise RuntimeError(
            f"Existing unmanaged database detected at {database_file}.\n"
            "This database was created outside Alembic (e.g. via create_all).\n"
            "Run `python -m forza maintenance db-reset --yes` to delete it, or back it\n"
            "up and remove it manually, then run `python -m forza maintenance db-upgrade`."
        )

    if state == DatabaseSchemaState.ERROR:
        raise RuntimeError(
            f"Could not inspect database at {database_file}. "
            "The file may be corrupt."
        )

    database_file.parent.mkdir(parents=True, exist_ok=True)
    cfg = _make_config(_db_url(database_file))
    command.upgrade(cfg, "head")


def ensure_db_ready(database_file: Path) -> None:
    """Ensure the database exists and is current before first use.

    Runs ``upgrade_database`` for all safe states. Normal CLI/GUI runtime paths
    must use ``require_db_ready`` instead so startup never mutates schema.
    """
    state = detect_database_state(database_file)
    if state in (
        DatabaseSchemaState.MISSING,
        DatabaseSchemaState.EMPTY,
        DatabaseSchemaState.OUTDATED,
        DatabaseSchemaState.CURRENT,
    ):
        # CURRENT is a no-op in Alembic's upgrade (already at head).
        upgrade_database(database_file)
    elif state == DatabaseSchemaState.UNMANAGED:
        raise RuntimeError(
            f"Unmanaged database at {database_file}. "
            "Run `python -m forza maintenance db-reset --yes` or remove the file, "
            "then retry."
        )
    # ERROR: let the subsequent engine creation fail with its own message.


def require_db_ready(database_file: Path) -> None:
    """Require an existing database at Alembic head without modifying it."""
    state = detect_database_state(database_file)
    if state == DatabaseSchemaState.CURRENT:
        return
    guidance = {
        DatabaseSchemaState.MISSING: "database does not exist",
        DatabaseSchemaState.EMPTY: "database is empty",
        DatabaseSchemaState.UNMANAGED: "database is unmanaged",
        DatabaseSchemaState.OUTDATED: "database is behind the migration head",
        DatabaseSchemaState.ERROR: "database state could not be inspected",
    }
    raise RuntimeError(
        f"DB vNext is not ready at {database_file}: {guidance.get(state, state.value)}. "
        "Run `python -m forza maintenance db-upgrade` explicitly."
    )


def current_revision(database_file: Path) -> str | None:
    """Return the current Alembic revision string, or None if uninitialized."""
    if not database_file.exists():
        return None
    engine = create_engine(_db_url(database_file))
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            return ctx.get_current_revision()
    except Exception:
        return None
    finally:
        engine.dispose()



def head_revision() -> str | None:
    """Return the Alembic head revision from the migration scripts."""
    try:
        cfg = _make_config("sqlite://")
        scripts = ScriptDirectory.from_config(cfg)
        return scripts.get_current_head()
    except Exception:
        return None


def is_up_to_date(database_file: Path) -> bool:
    """Return True if the database is at the Alembic head revision."""
    state = detect_database_state(database_file)
    return state == DatabaseSchemaState.CURRENT
