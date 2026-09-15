// Test harness: unwraps are idiomatic assertion helpers here.
#![allow(clippy::unwrap_used, clippy::expect_used)]

//! Schema lifecycle tests: create-from-zero, version stamping, idempotence,
//! and refusal to touch foreign-version databases.

use forza_db::SCHEMA_VERSION;
use forza_db::migration::{SchemaStatus, schema_status, upgrade};
use std::path::Path;

#[test]
fn empty_path_reports_empty_then_upgrades_to_current() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("fresh.sqlite3");

    assert_eq!(schema_status(&path).unwrap(), SchemaStatus::Empty);
    upgrade(&path).unwrap();
    assert_eq!(
        schema_status(&path).unwrap(),
        SchemaStatus::Current,
        "expected user_version == {SCHEMA_VERSION}"
    );
}

#[test]
fn upgrade_is_idempotent_on_current_database() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("idem.sqlite3");
    upgrade(&path).unwrap();
    let before = std::fs::read(&path).unwrap();
    upgrade(&path).unwrap();
    let after = std::fs::read(&path).unwrap();
    assert_eq!(before.len(), after.len());
}

#[test]
fn created_schema_contains_every_baseline_table_and_index() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("full.sqlite3");
    upgrade(&path).unwrap();
    let conn = rusqlite::Connection::open(&path).unwrap();

    let tables: Vec<String> = {
        let mut stmt = conn
            .prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
            .unwrap();
        stmt.query_map([], |r| r.get(0))
            .unwrap()
            .collect::<Result<_, _>>()
            .unwrap()
    };
    for expected in [
        "alembic_version",
        "export_artifacts",
        "external_lap_records",
        "external_record_imports",
        "extraction_attempts",
        "extraction_results",
        "extraction_runs",
        "image_files",
        "image_flags",
        "lap_records",
        "model_artifacts",
        "model_runtime_snapshots",
        "prompt_snapshots",
        "reference_cars",
        "reference_tracks",
        "review_cases",
        "review_corrections",
        "run_inputs",
    ] {
        assert!(
            tables.iter().any(|t| t == expected),
            "missing table {expected}"
        );
    }

    let indexes: Vec<String> = {
        let mut stmt = conn
            .prepare("SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")
            .unwrap();
        stmt.query_map([], |r| r.get(0))
            .unwrap()
            .collect::<Result<_, _>>()
            .unwrap()
    };
    assert!(
        indexes
            .iter()
            .any(|i| i == "idx_attempts_one_accepted_per_result"),
        "partial unique index missing"
    );
    assert!(
        indexes
            .iter()
            .any(|i| i == "idx_runtime_one_preflight_per_run"),
        "partial unique index missing"
    );
}

#[test]
fn populated_foreign_version_database_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("legacy.sqlite3");
    {
        let conn = rusqlite::Connection::open(&path).unwrap();
        conn.execute_batch(
            "CREATE TABLE some_table (id TEXT PRIMARY KEY);
             PRAGMA user_version = 999;",
        )
        .unwrap();
    }
    match upgrade(&path) {
        Err(forza_db::DbError::SchemaState { message }) => {
            assert!(message.contains("refusing"), "{message}");
        }
        other => panic!("expected schema refusal, got {other:?}"),
    }
}

#[test]
fn empty_file_with_zero_tables_is_still_empty() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("zero.sqlite3");
    std::fs::File::create(&path).unwrap();
    assert_eq!(
        schema_status(Path::new(&path)).unwrap(),
        SchemaStatus::Empty
    );
}
