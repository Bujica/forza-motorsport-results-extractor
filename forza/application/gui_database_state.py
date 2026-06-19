from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..db.migrate import DatabaseSchemaState, detect_database_state, upgrade_database
from .reference_seed import seed_initial_reference_text_files


@dataclass(frozen=True)
class DatabaseCheckResult:
    path: Path
    state: DatabaseSchemaState
    opened: bool
    message: str


_BLOCKED_MESSAGES = {
    DatabaseSchemaState.UNMANAGED: (
        "Database is not compatible with the current schema. You can reset it "
        "from the GUI, or run `python -m forza maintenance db-reset --yes` "
        "after making a backup."
    ),
    DatabaseSchemaState.ERROR: "Could not inspect the database. The file may be corrupted.",
}


def inspect_database(path: Path) -> DatabaseCheckResult:
    state = detect_database_state(path)
    if state == DatabaseSchemaState.CURRENT:
        return DatabaseCheckResult(path, state, True, "Database is current.")
    if state in _BLOCKED_MESSAGES:
        return DatabaseCheckResult(path, state, False, _BLOCKED_MESSAGES[state])
    return DatabaseCheckResult(path, state, False, _upgrade_prompt(state))


def apply_database_upgrade(path: Path) -> DatabaseCheckResult:
    try:
        upgrade_database(path)
        added_tracks, added_cars = seed_initial_reference_text_files(path)
    except RuntimeError as exc:
        state = detect_database_state(path)
        return DatabaseCheckResult(path, state, False, str(exc))

    state = detect_database_state(path)
    opened = state == DatabaseSchemaState.CURRENT
    message = (
        f"Database created or upgraded. Seeded references: {added_tracks} track(s), {added_cars} car(s) added."
        if opened
        else f"Unexpected state after upgrade: {state.value}"
    )
    return DatabaseCheckResult(path, state, opened, message)


def apply_database_reset(path: Path) -> DatabaseCheckResult:
    removed = 0
    try:
        for target in _sqlite_database_files(path):
            if target.exists():
                target.unlink()
                removed += 1
    except OSError as exc:
        state = detect_database_state(path)
        return DatabaseCheckResult(path, state, False, f"Could not reset database: {exc}")

    result = apply_database_upgrade(path)
    if not result.opened:
        return result
    return DatabaseCheckResult(
        path,
        result.state,
        True,
        f"Database reset and recreated. Removed {removed} file(s). {result.message}",
    )


def _sqlite_database_files(path: Path) -> tuple[Path, Path, Path]:
    return (path, Path(f"{path}-wal"), Path(f"{path}-shm"))


def _upgrade_prompt(state: DatabaseSchemaState) -> str:
    if state in (DatabaseSchemaState.MISSING, DatabaseSchemaState.EMPTY):
        return (
            "Database is missing or empty. Create the database now? "
            "The upgrade is idempotent and safe to repeat."
        )
    if state == DatabaseSchemaState.OUTDATED:
        return (
            "Database is outdated. Upgrade is required before opening the GUI. "
            "The upgrade is idempotent and safe to repeat."
        )
    return f"Database state: {state.value}"
