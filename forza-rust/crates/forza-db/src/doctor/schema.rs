//! Schema-drift checks (schema_checks.py).

use std::collections::BTreeMap;

use rusqlite::Connection;

use crate::error::DbError;
use crate::schema_ddl::{INDEX_DDL, TABLE_DDL};

use super::types::{DoctorCheck, DoctorSeverity};

// ── Schema drift checks (schema_checks.py) ───────────────────────────────────

const VOCABULARY_CHECKS: &[(&str, &str)] = &[
    ("image_files", "ck_image_files_file_status_vocab"),
    ("image_files", "ck_image_files_best_lap_status_vocab"),
    ("extraction_runs", "ck_extraction_runs_status_vocab"),
    ("extraction_runs", "ck_extraction_runs_mode_vocab"),
    ("run_inputs", "ck_run_inputs_decision_vocab"),
    ("run_inputs", "ck_run_inputs_duplicate_kind_vocab"),
    ("extraction_results", "ck_extraction_results_status_vocab"),
    ("extraction_attempts", "ck_extraction_attempts_status_vocab"),
    ("review_cases", "ck_review_cases_status_vocab"),
    ("review_cases", "ck_review_cases_outcome_vocab"),
    ("review_cases", "ck_review_cases_reason_vocab"),
    ("review_cases", "ck_review_cases_trigger_vocab"),
    ("review_cases", "ck_review_cases_decision_field_vocab"),
    ("image_flags", "ck_image_flags_status_vocab"),
    ("image_flags", "ck_image_flags_scope_vocab"),
    ("image_flags", "ck_image_flags_flag_type_vocab"),
    ("review_corrections", "ck_review_corrections_field_vocab"),
    ("review_corrections", "ck_review_corrections_cause_vocab"),
    (
        "external_record_imports",
        "ck_external_record_imports_status_vocab",
    ),
    (
        "external_lap_records",
        "ck_external_lap_records_weather_vocab",
    ),
];

const EXPECTED_SERVER_DEFAULTS: &[(&str, &[(&str, &str)])] = &[
    (
        "extraction_runs",
        &[
            ("status", "'pending'"),
            ("mode", "'normal'"),
            ("backend", "'lmstudio'"),
            ("workers", "1"),
            ("grayscale", "0"),
            ("total_inputs", "0"),
            ("to_process", "0"),
            ("processed", "0"),
            ("succeeded", "0"),
            ("failed", "0"),
            ("skipped", "0"),
            ("duplicate_count", "0"),
            ("review_case_count", "0"),
        ],
    ),
    (
        "image_files",
        &[
            ("race_datetime_source", "'file_modified_at'"),
            ("file_status", "'available'"),
            ("best_lap_status", "'pending'"),
        ],
    ),
    (
        "model_runtime_snapshots",
        &[("snapshot_kind", "'preflight'"), ("health_ok", "0")],
    ),
    ("extraction_results", &[("attempt_count", "0")]),
    ("extraction_attempts", &[("accepted", "0")]),
    ("model_artifacts", &[("is_canonical", "0")]),
    (
        "external_record_imports",
        &[
            ("total_rows", "0"),
            ("accepted_rows", "0"),
            ("rejected_rows", "0"),
            ("issue_count", "0"),
        ],
    ),
    (
        "lap_records",
        &[
            ("source_file", "''"),
            ("driver", "''"),
            ("driver_normalized", "''"),
            ("car", "''"),
            ("car_normalized", "''"),
            ("race_class", "''"),
            ("track", "''"),
            ("track_normalized", "''"),
            ("weather", "'unknown'"),
            ("best_lap", "''"),
            ("best_lap_ms", "0"),
            ("dirty", "0"),
            ("is_best_lap", "0"),
        ],
    ),
    (
        "review_cases",
        &[
            ("status", "'open'"),
            ("source_file", "''"),
            ("weather", "'unknown'"),
        ],
    ),
    ("review_corrections", &[("cause", "'unknown'")]),
    (
        "image_flags",
        &[
            ("flag_scope", "'image'"),
            ("status", "'active'"),
            ("created_by", "'system'"),
        ],
    ),
];

/// An in-memory database built from the shipped DDL constants, used as the
/// expected baseline for schema drift checks.
fn expected_schema_db() -> Result<Connection, DbError> {
    let conn = Connection::open_in_memory()?;
    for statement in TABLE_DDL {
        conn.execute_batch(statement)?;
    }
    for statement in INDEX_DDL {
        conn.execute_batch(statement)?;
    }
    Ok(conn)
}

const SCHEMA_OBJECTS_SQL: &str = "SELECT type, name, sql FROM sqlite_master
     WHERE type IN ('table', 'index', 'view')
       AND name NOT LIKE 'sqlite_%'
       AND name <> 'alembic_version'";

fn schema_objects(conn: &Connection) -> Result<BTreeMap<(String, String), String>, DbError> {
    let mut stmt = conn.prepare(SCHEMA_OBJECTS_SQL)?;
    let rows = stmt.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, Option<String>>(2)?,
        ))
    })?;
    let mut map = BTreeMap::new();
    for row in rows {
        let (kind, name, sql) = row?;
        map.insert((kind, name), normalize_schema_sql(sql.as_deref()));
    }
    Ok(map)
}

fn normalize_schema_sql(value: Option<&str>) -> String {
    match value {
        None => String::new(),
        Some(sql) => sql
            .split_whitespace()
            .collect::<Vec<_>>()
            .join(" ")
            .to_lowercase(),
    }
}

fn table_columns(conn: &Connection, table: &str) -> Result<Vec<String>, DbError> {
    let mut stmt = conn.prepare(&format!("PRAGMA table_info(\"{table}\")"))?;
    let rows = stmt.query_map([], |row| row.get::<_, String>(1))?;
    rows.collect::<Result<Vec<_>, _>>().map_err(DbError::from)
}

pub(super) fn schema_drift_checks(conn: &Connection) -> Result<Vec<DoctorCheck>, DbError> {
    // Vocabulary constraints: every expected CHECK name must appear in the
    // stored CREATE TABLE statement.
    let mut vocabulary_missing = 0i64;
    {
        let mut stmt =
            conn.prepare("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?1")?;
        for (table_name, constraint_name) in VOCABULARY_CHECKS {
            let create_sql: Option<String> = stmt
                .query_row([table_name], |row| row.get(0))
                .unwrap_or(None);
            let present = create_sql
                .as_deref()
                .is_some_and(|sql| sql.contains(constraint_name));
            if !present {
                vocabulary_missing += 1;
            }
        }
    }
    let vocabulary_check = DoctorCheck::new(
        "vocabulary_check_constraints_missing",
        DoctorSeverity::Error,
        "SQLite schema must enforce clean-break vocabulary CHECK constraints.",
        vocabulary_missing,
    );

    // Column drift: compare actual columns against the in-memory baseline DB.
    let expected_conn = expected_schema_db()?;
    let expected_tables = {
        let mut stmt = expected_conn.prepare(
            "SELECT name FROM sqlite_master
             WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name <> 'alembic_version'",
        )?;
        let rows = stmt.query_map([], |row| row.get::<_, String>(0))?;
        rows.collect::<Result<Vec<_>, _>>()?
    };

    let mut column_drift = 0i64;
    for table in &expected_tables {
        let expected_columns = table_columns(&expected_conn, table)?;
        let actual_columns = table_columns(conn, table)?;
        let mut expected: Vec<&str> = expected_columns.iter().map(String::as_str).collect();
        let mut actual: Vec<&str> = actual_columns.iter().map(String::as_str).collect();
        expected.sort_unstable();
        actual.sort_unstable();
        column_drift += expected.iter().filter(|c| !actual.contains(c)).count() as i64;
        column_drift += actual.iter().filter(|c| !expected.contains(c)).count() as i64;
    }
    let column_drift_check = DoctorCheck::new(
        "schema_column_drift",
        DoctorSeverity::Error,
        "Effective SQLite columns must match the current DB vNext model.",
        column_drift,
    );

    // Server default drift: PRAGMA dflt_value must match the frozen contract.
    let mut default_drift = 0i64;
    for (table, defaults) in EXPECTED_SERVER_DEFAULTS {
        let mut stmt = conn.prepare(&format!("PRAGMA table_info(\"{table}\")"))?;
        let rows = stmt.query_map([], |row| {
            Ok((row.get::<_, String>(1)?, row.get::<_, Option<String>>(4)?))
        })?;
        let mut actual: BTreeMap<String, Option<String>> = BTreeMap::new();
        for row in rows {
            let (column, dflt) = row?;
            actual.insert(column, dflt);
        }
        for (column, default) in *defaults {
            if actual.get(*column).and_then(|v| v.as_deref()) != Some(*default) {
                default_drift += 1;
            }
        }
    }
    let default_drift_check = DoctorCheck::new(
        "schema_server_default_drift",
        DoctorSeverity::Error,
        "Effective SQLite server defaults must match the DB vNext contract.",
        default_drift,
    );

    // Frozen SQL drift: normalized sqlite_master entries must match baseline.
    let expected_objects = schema_objects(&expected_conn)?;
    let actual_objects = schema_objects(conn)?;
    let mut frozen_drift = 0i64;
    for key in expected_objects.keys().chain(actual_objects.keys()) {
        if expected_objects.get(key) != actual_objects.get(key) {
            frozen_drift += 1;
        }
    }
    let frozen_drift_check = DoctorCheck::new(
        "frozen_schema_sql_drift",
        DoctorSeverity::Error,
        "Effective tables, constraints, foreign keys, indexes, and views must match the frozen baseline SQL.",
        frozen_drift,
    );

    Ok(vec![
        vocabulary_check,
        column_drift_check,
        default_drift_check,
        frozen_drift_check,
    ])
}
