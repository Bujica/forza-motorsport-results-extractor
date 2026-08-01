from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from ..config import load_config
from ..logging_setup import setup_logging
from ..application import DatabaseService
from ..application.reference_seed import seed_initial_reference_text_files


def cmd_db_status(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    setup_logging(cfg.log_file, debug=args.debug)
    # DatabaseService.status() is read-only — does not create the database.
    with DatabaseService(cfg.database_file) as database:
        status = database.status()

    print(f"Database: {status.database_file}")
    print(f"Exists:   {status.database_exists}")
    print(f"Schema:   {status.schema_state}")
    print(f"Revision: {status.current_revision or '(none)'}")
    print(f"Head:     {status.head_revision or '(none)'}")
    print("")
    print("Relational store")
    print(f"  image_files     : {status.image_files}")
    print(f"  extraction_runs : {status.extraction_runs}")
    print(f"  extraction_results: {status.extraction_results}")
    print(f"  extraction_attempts: {getattr(status, 'extraction_attempts', 0)}")
    print(f"  lap_records       : {status.lap_records}")
    print(f"  review_cases      : {status.review_cases}")
    print(f"  image_flags       : {status.image_flags}")
    print(f"  export_artifacts  : {status.export_artifacts}")
    print(f"  reference_tracks  : {getattr(status, 'reference_tracks', 0)}")
    print(f"  reference_cars    : {getattr(status, 'reference_cars', 0)}")
    print(f"  external_imports  : {getattr(status, 'external_record_imports', 0)}")
    print(f"  external_laps     : {getattr(status, 'external_lap_records', 0)}")


def cmd_db_reset(args: argparse.Namespace) -> None:
    """Delete the configured SQLite database and sidecar files."""
    if not args.yes:
        raise SystemExit("Refusing to reset database without --yes")

    cfg = load_config(args.config)
    database_file = Path(cfg.database_file)

    if database_file.exists():
        _ensure_exclusive_access(database_file)

    wal_file = Path(f"{database_file}-wal")
    shm_file = Path(f"{database_file}-shm")
    if wal_file.exists() or shm_file.exists():
        print(
            "WARNING: WAL/SHM sidecar file(s) present — this can mean a "
            "connection had the database open recently. Proceeding since no "
            "connection currently holds an exclusive lock."
        )

    targets = [database_file, wal_file, shm_file]
    removed: list[Path] = []
    for target in targets:
        if target.exists():
            target.unlink()
            removed.append(target)

    print("Database reset")
    print(f"Removed: {len(removed)} file(s)")
    for target in removed:
        print(f"  - {target}")


def _ensure_exclusive_access(database_file: Path) -> None:
    """Abort instead of deleting if another connection currently holds the database.

    Deleting a SQLite file out from under an open connection can corrupt
    whatever that connection was mid-write on (see audit finding C-2).
    Requesting an EXCLUSIVE lock surfaces an in-use database as a clear error
    instead of a silent race. A file that fails to open because it isn't a
    valid SQLite database at all (``sqlite3.DatabaseError``) is a legitimate
    reason to run db-reset in the first place, so that case is not blocked —
    only an actual lock held by another connection is (``sqlite3.OperationalError``).
    """
    conn = sqlite3.connect(str(database_file), timeout=0)
    try:
        conn.execute("PRAGMA locking_mode=EXCLUSIVE")
        conn.execute("BEGIN EXCLUSIVE")
        conn.execute("COMMIT")
    except sqlite3.OperationalError as exc:
        raise SystemExit(
            f"Refusing to reset database: {database_file} appears to be in use by "
            f"another connection ({exc}). Close any running Forza processes (GUI, "
            "CLI runs, or scripts) and try again."
        ) from exc
    except sqlite3.DatabaseError:
        # Not a valid SQLite file at all — resetting is the legitimate fix.
        pass
    finally:
        conn.close()


def cmd_db_upgrade(args: argparse.Namespace) -> None:
    """Apply all pending Alembic migrations."""
    from ..db.migrate import DatabaseSchemaState, detect_database_state, upgrade_database

    cfg = load_config(args.config)
    setup_logging(cfg.log_file, debug=getattr(args, "debug", False))

    state = detect_database_state(cfg.database_file)
    if state == DatabaseSchemaState.UNMANAGED:
        print(f"ERROR: Unmanaged database detected at {cfg.database_file}")
        print("       It has tables but no alembic_version; Alembic cannot manage it.")
        print("       Run: python -m forza maintenance db-reset --yes")
        print("       Then retry: python -m forza maintenance db-upgrade")
        raise SystemExit(1)

    print(f"Upgrading database: {cfg.database_file}")
    upgrade_database(cfg.database_file)
    added_tracks, added_cars = seed_initial_reference_text_files(cfg.database_file)
    print(f"Seeded references: {added_tracks} track(s), {added_cars} car(s) added.")
    print("Done.")


def cmd_db_doctor(args: argparse.Namespace) -> None:
    """Report relational integrity issues that matter before release/reruns."""
    from ..application import DbDoctorService

    cfg = load_config(args.config)
    setup_logging(cfg.log_file, debug=getattr(args, "debug", False))
    report = DbDoctorService().run(cfg.database_file)
    if getattr(args, "json", False):
        print(json.dumps({
            "database_file": str(report.database_file),
            "schema_state": report.schema_state,
            "ok": report.ok,
            "checks": [
                {
                    "key": check.key,
                    "severity": check.severity,
                    "count": check.count,
                    "detail": check.detail,
                    "ok": check.ok,
                }
                for check in report.checks
            ],
        }, indent=2))
    else:
        _print_db_doctor_report(report)
    if not report.ok:
        raise SystemExit(2)


def _print_db_doctor_report(report) -> None:
    print(f"Database: {report.database_file}")
    print(f"Schema:   {report.schema_state}")
    print(f"OK:       {report.ok}")
    for check in report.checks:
        status = "OK" if check.ok else check.severity.upper()
        print(f"[{status}] {check.key}: {check.count} - {check.detail}")


def cmd_config_check(args: argparse.Namespace) -> None:
    """Validate forza_config.ini and report any errors."""
    from ..config import validate_config
    from ..exceptions import ConfigValidationError

    try:
        cfg = load_config(args.config)
    except Exception as exc:
        print(f"ERROR: Could not load config: {exc}")
        raise SystemExit(1)

    try:
        validate_config(cfg)
        print(f"Configuration is valid. ({args.config})")
    except ConfigValidationError as exc:
        print(str(exc))
        raise SystemExit(1)
