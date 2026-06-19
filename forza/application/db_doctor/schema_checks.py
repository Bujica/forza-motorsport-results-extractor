from __future__ import annotations

from pathlib import Path
import re
import sqlite3

from sqlalchemy import text
from sqlmodel import Session

from .contracts import DbDoctorCheck
from ...db.models import (
    ExtractionAttemptEntity,
    ExtractionResultEntity,
    ExtractionRunEntity,
    ExportArtifactEntity,
    ExternalLapRecordEntity,
    ExternalRecordImportEntity,
    ImageFileEntity,
    ImageFlagEntity,
    LapRecordEntity,
    ModelArtifactEntity,
    ModelRuntimeSnapshotEntity,
    PromptSnapshotEntity,
    ReferenceCarEntity,
    ReferenceTrackEntity,
    ReviewCaseEntity,
    ReviewCorrectionEntity,
    RunInputEntity,
)

_EXPECTED_SCHEMA_MIGRATION_REVISIONS = ()

_SCHEMA_DRIFT_ENTITY_TYPES = (
    PromptSnapshotEntity,
    ImageFileEntity,
    ExtractionRunEntity,
    RunInputEntity,
    ModelRuntimeSnapshotEntity,
    ExtractionResultEntity,
    ExtractionAttemptEntity,
    ModelArtifactEntity,
    LapRecordEntity,
    ReviewCaseEntity,
    ImageFlagEntity,
    ReviewCorrectionEntity,
    ExportArtifactEntity,
    ReferenceCarEntity,
    ReferenceTrackEntity,
    ExternalRecordImportEntity,
    ExternalLapRecordEntity,
)


def schema_drift_checks(session: Session) -> list[DbDoctorCheck]:
    return [
        DbDoctorCheck(
            "vocabulary_check_constraints_missing",
            "error",
            _vocabulary_check_constraints_missing(session),
            "SQLite schema must enforce clean-break vocabulary CHECK constraints.",
        ),
        DbDoctorCheck(
            "schema_column_drift",
            "error",
            _schema_column_drift(session),
            "Effective SQLite columns must match the current DB vNext model.",
        ),
        DbDoctorCheck(
            "schema_server_default_drift",
            "error",
            _schema_server_default_drift(session),
            "Effective SQLite server defaults must match the DB vNext contract.",
        ),
        DbDoctorCheck(
            "frozen_schema_sql_drift",
            "error",
            _frozen_schema_sql_drift(session),
            "Effective tables, constraints, foreign keys, indexes, and views must match the frozen baseline SQL.",
        ),
    ]

VOCABULARY_CHECKS = [('image_files', 'ck_image_files_file_status_vocab', "file_status IN ('available', 'missing')"), ('image_files', 'ck_image_files_best_lap_status_vocab', "best_lap_status IN ('pending', 'contributing', 'non_contributing')"), ('extraction_runs', 'ck_extraction_runs_status_vocab', "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')"), ('extraction_runs', 'ck_extraction_runs_mode_vocab', "mode IN ('normal', 'dry_run')"), ('run_inputs', 'ck_run_inputs_decision_vocab', "decision IN ('process', 'skip', 'duplicate', 'missing', 'unsupported', 'outside_input', 'hash_failed')"), ('run_inputs', 'ck_run_inputs_duplicate_kind_vocab', "duplicate_kind IS NULL OR duplicate_kind IN ('hash', 'batch')"), ('extraction_results', 'ck_extraction_results_status_vocab', "status IN ('pending', 'running', 'ok', 'error', 'cancelled')"), ('extraction_attempts', 'ck_extraction_attempts_status_vocab', "status IN ('ok', 'error', 'cancelled')"), ('review_cases', 'ck_review_cases_status_vocab', "status IN ('open', 'resolved', 'ignored', 'auto_resolved')"), ('review_cases', 'ck_review_cases_outcome_vocab', "outcome IN ('pending', 'confirmed', 'model_error', 'ignored')"), ('review_cases', 'ck_review_cases_reason_vocab', "reason IN ('dirty_lap', 'track', 'weather', 'race_class', 'car', 'driver_name')"), ('review_cases', 'ck_review_cases_trigger_vocab', "\"trigger\" IS NULL OR \"trigger\" IN ('model_marked_dirty', 'weather_unknown', 'rain_time_suspicious', 'track_unknown', 'track_unresolved', 'track_not_in_reference', 'class_unknown', 'class_invalid', 'car_empty', 'car_not_in_reference', 'driver_name_empty', 'numeric_prefix', 'invalid_symbol')"), ('review_cases', 'ck_review_cases_decision_field_vocab', "decision_field IS NULL OR decision_field IN ('dirty', 'track', 'weather', 'race_class', 'car', 'driver')"), ('image_flags', 'ck_image_flags_status_vocab', "status IN ('active', 'resolved', 'ignored')"), ('image_flags', 'ck_image_flags_scope_vocab', "flag_scope IN ('image', 'lap')"), ('image_flags', 'ck_image_flags_flag_type_vocab', "flag_type IN ('duplicate', 'dirty_lap', 'track', 'weather', 'race_class', 'car', 'driver_name')"), ('review_corrections', 'ck_review_corrections_field_vocab', "field IN ('dirty', 'track', 'weather', 'race_class', 'car', 'driver')"), ('review_corrections', 'ck_review_corrections_cause_vocab', "cause IN ('review', 'rebuild', 'auto', 'unknown')"), ('external_record_imports', 'ck_external_record_imports_status_vocab', "status IN ('pending', 'active', 'failed')"), ('external_lap_records', 'ck_external_lap_records_weather_vocab', "weather IN ('dry', 'rain', 'unknown')")]

_EXPECTED_SERVER_DEFAULTS = {
    "extraction_runs": {
        "status": "'pending'",
        "mode": "'normal'",
        "backend": "'lmstudio'",
        "workers": "1",
        "grayscale": "0",
        "total_inputs": "0",
        "to_process": "0",
        "processed": "0",
        "succeeded": "0",
        "failed": "0",
        "skipped": "0",
        "duplicate_count": "0",
        "review_case_count": "0",
    },
    "image_files": {
        "race_datetime_source": "'file_modified_at'",
        "file_status": "'available'",
        "best_lap_status": "'pending'",
    },
    "model_runtime_snapshots": {"snapshot_kind": "'preflight'", "health_ok": "0"},
    "extraction_results": {"attempt_count": "0"},
    "extraction_attempts": {"accepted": "0"},
    "model_artifacts": {"is_canonical": "0"},
    "external_record_imports": {
        "total_rows": "0",
        "accepted_rows": "0",
        "rejected_rows": "0",
        "issue_count": "0",
    },
    "lap_records": {
        "source_file": "''",
        "driver": "''",
        "driver_normalized": "''",
        "car": "''",
        "car_normalized": "''",
        "race_class": "''",
        "track": "''",
        "track_normalized": "''",
        "weather": "'unknown'",
        "best_lap": "''",
        "best_lap_ms": "0",
        "dirty": "0",
        "is_best_lap": "0",
    },
    "review_cases": {"status": "'open'", "source_file": "''", "weather": "'unknown'"},
    "review_corrections": {"cause": "'unknown'"},
    "image_flags": {
        "flag_scope": "'image'",
        "status": "'active'",
        "created_by": "'system'",
    },
}


def _vocabulary_check_constraints_missing(session: Session) -> int:
    missing = 0
    for table_name, constraint_name, _expression in VOCABULARY_CHECKS:
        row = session.exec(text(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = :table_name"
        ).bindparams(table_name=table_name)).first()
        create_sql = str(row[0] if isinstance(row, tuple) or hasattr(row, "__getitem__") else row or "")
        if constraint_name not in create_sql:
            missing += 1
    return missing


def _add_vocabulary_check_constraints(connection: sqlite3.Connection) -> None:
    views = _drop_sqlite_views(connection)
    try:
        grouped: dict[str, list[tuple[str, str]]] = {}
        for table_name, constraint_name, expression in VOCABULARY_CHECKS:
            grouped.setdefault(table_name, []).append((constraint_name, expression))
        for table_name, constraints in grouped.items():
            _add_check_constraints_to_sqlite_table(connection, table_name, constraints)
    finally:
        _restore_sqlite_views(connection, views)


def _drop_sqlite_views(connection: sqlite3.Connection) -> list[tuple[str, str]]:
    rows = connection.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type = 'view' AND sql IS NOT NULL "
        "ORDER BY name"
    ).fetchall()
    views = [(str(row[0]), str(row[1])) for row in rows]
    for name, _sql in reversed(views):
        connection.execute('DROP VIEW IF EXISTS "' + name + '"')
    return views


def _restore_sqlite_views(connection: sqlite3.Connection, views: list[tuple[str, str]]) -> None:
    for _name, sql in views:
        connection.execute(sql)


def _add_check_constraints_to_sqlite_table(
    connection: sqlite3.Connection,
    table_name: str,
    constraints: list[tuple[str, str]],
) -> None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    if row is None or not row[0]:
        return

    create_sql = str(row[0])
    missing = [(name, expression) for name, expression in constraints if name not in create_sql]
    if not missing:
        return

    index_rows = connection.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL "
        "ORDER BY name",
        (table_name,),
    ).fetchall()
    index_sql = [str(row[1]) for row in index_rows if row[1]]
    columns = [
        str(row[1])
        for row in connection.execute("PRAGMA table_info(" + table_name + ")").fetchall()
    ]
    column_list = ", ".join('"' + column + '"' for column in columns)
    tmp_table = "__tmp_" + table_name + "_vocab_checks"

    tmp_sql = _create_sql_for_tmp_table(create_sql, table_name, tmp_table)
    tmp_sql = _inject_vocabulary_check_constraints(tmp_sql, missing)

    connection.execute('DROP TABLE IF EXISTS "' + tmp_table + '"')
    connection.execute(tmp_sql)
    connection.execute(
        'INSERT INTO "'
        + tmp_table
        + '" ('
        + column_list
        + ') SELECT '
        + column_list
        + ' FROM "'
        + table_name
        + '"'
    )
    connection.execute('DROP TABLE "' + table_name + '"')
    connection.execute('ALTER TABLE "' + tmp_table + '" RENAME TO "' + table_name + '"')
    for sql in index_sql:
        connection.execute(sql)


def _create_sql_for_tmp_table(create_sql: str, table_name: str, tmp_table: str) -> str:
    prefixes = (
        "CREATE TABLE " + table_name,
        'CREATE TABLE "' + table_name + '"',
    )
    for prefix in prefixes:
        if create_sql.startswith(prefix):
            return create_sql.replace(prefix, 'CREATE TABLE "' + tmp_table + '"', 1)
    marker = "CREATE TABLE " + table_name
    if marker in create_sql:
        return create_sql.replace(marker, 'CREATE TABLE "' + tmp_table + '"', 1)
    raise RuntimeError("Unsupported CREATE TABLE SQL for " + table_name + ": " + create_sql)


def _inject_vocabulary_check_constraints(create_sql: str, constraints: list[tuple[str, str]]) -> str:
    sql = create_sql.rstrip()
    if not sql.endswith(")"):
        raise RuntimeError("Unsupported CREATE TABLE SQL: " + create_sql)
    additions = "".join(
        ",\n\tCONSTRAINT " + name + " CHECK (" + expression + ")"
        for name, expression in constraints
    )
    return sql[:-1] + additions + "\n)"

def _schema_column_drift(session: Session) -> int:
    drift = 0
    for entity_type in _SCHEMA_DRIFT_ENTITY_TYPES:
        table = entity_type.__table__
        expected = {column.name for column in table.columns}
        rows = session.exec(text(f"PRAGMA table_info({_sqlite_identifier(table.name)})")).all()
        actual = {str(row[1]) for row in rows}
        drift += len(expected.symmetric_difference(actual))
    return drift


def _schema_server_default_drift(session: Session) -> int:
    drift = 0
    for table, expected in _EXPECTED_SERVER_DEFAULTS.items():
        rows = session.exec(text(f"PRAGMA table_info({_sqlite_identifier(table)})")).all()
        actual = {str(row[1]): row[4] for row in rows}
        for column, default in expected.items():
            if str(actual.get(column)) != default:
                drift += 1
    return drift


def _frozen_schema_sql_drift(session: Session) -> int:
    schema_dir = (
        Path(__file__).resolve().parents[2]
        / "db"
        / "migrations"
        / "versions"
    )
    with sqlite3.connect(":memory:") as expected_db:
        for schema_file in (
            "0001_db_vnext_schema.sql",
        ):
            expected_db.executescript((schema_dir / schema_file).read_text(encoding="utf-8"))
        _apply_expected_schema_migrations(expected_db)
        expected = _sqlite_schema_objects(expected_db)
    actual_rows = session.exec(text("""
        SELECT type, name, sql
        FROM sqlite_master
        WHERE type IN ('table', 'index', 'view')
          AND name NOT LIKE 'sqlite_%'
          AND name <> 'alembic_version'
    """)).all()
    actual = {
        (str(row[0]), str(row[1])): _normalize_schema_sql(row[2])
        for row in actual_rows
    }
    keys = set(expected) | set(actual)
    return sum(1 for key in keys if expected.get(key) != actual.get(key))


def _sqlite_schema_objects(connection: sqlite3.Connection) -> dict[tuple[str, str], str]:
    return {
        (str(row[0]), str(row[1])): _normalize_schema_sql(row[2])
        for row in connection.execute("""
            SELECT type, name, sql
            FROM sqlite_master
            WHERE type IN ('table', 'index', 'view')
              AND name NOT LIKE 'sqlite_%'
        """)
    }


def _apply_expected_schema_migrations(connection: sqlite3.Connection) -> None:
    """No post-baseline schema migrations remain after the clean-break squash."""
    return


def _sqlite_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _normalize_schema_sql(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip().casefold()
