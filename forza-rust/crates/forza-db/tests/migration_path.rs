//! v2 → v3 migration: the three `performance_*` columns go away, data stays.

// Test harness code: unwraps are the idiomatic assertion helpers here.
#![allow(clippy::unwrap_used)]

use forza_db::{MigrateOutcome, SchemaStatus, schema_status};
use forza_db::{backup_database, migrate, open_connection, upgrade};

fn v2_database(path: &std::path::Path) {
    upgrade(path).unwrap();
    let conn = open_connection(path).unwrap();
    // Re-add the removed columns to simulate a v2 database, with values.
    conn.execute_batch(
        "ALTER TABLE extraction_runs ADD COLUMN performance_tps_floor FLOAT;
         ALTER TABLE extraction_runs ADD COLUMN performance_reload_elapsed_s FLOAT;
         ALTER TABLE extraction_runs ADD COLUMN performance_reload_streak INTEGER;
         INSERT INTO extraction_runs
            (id, model, created_at, performance_tps_floor,
             performance_reload_elapsed_s, performance_reload_streak)
          VALUES ('run-v2', 'm', datetime('now'), 20.0, 45.0, 3);
         PRAGMA user_version = 2;",
    )
    .unwrap();
    assert!(matches!(
        schema_status(path).unwrap(),
        SchemaStatus::Incompatible { found: 2 }
    ));
}

#[test]
fn migrate_v2_to_v3_drops_columns_and_keeps_rows() {
    let dir = tempfile::tempdir().unwrap();
    let db = dir.path().join("v2.sqlite3");
    v2_database(&db);

    let outcome = migrate(&db).unwrap();
    assert_eq!(outcome, MigrateOutcome::Migrated { from: 2 });
    assert!(matches!(schema_status(&db).unwrap(), SchemaStatus::Current));

    let conn = open_connection(&db).unwrap();
    let columns: Vec<String> = conn
        .prepare("PRAGMA table_info(\"extraction_runs\")")
        .unwrap()
        .query_map([], |row| row.get::<_, String>(1))
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap();
    for dropped in [
        "performance_tps_floor",
        "performance_reload_elapsed_s",
        "performance_reload_streak",
    ] {
        assert!(!columns.contains(&dropped.to_string()), "{columns:?}");
    }
    // The run row survives the migration (only the dead columns go away).
    let count: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM extraction_runs WHERE id = 'run-v2'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(count, 1);
}

#[test]
fn migrate_refuses_unknown_versions() {
    let dir = tempfile::tempdir().unwrap();
    let db = dir.path().join("foreign.sqlite3");
    upgrade(&db).unwrap();
    let conn = open_connection(&db).unwrap();
    conn.execute_batch("PRAGMA user_version = 424242").unwrap();
    drop(conn);
    let err = migrate(&db).unwrap_err().to_string();
    assert!(err.contains("no migration path"), "{err}");
}

#[test]
fn backup_database_copies_next_to_source() {
    let dir = tempfile::tempdir().unwrap();
    let db = dir.path().join("live.sqlite3");
    upgrade(&db).unwrap();
    let backup = backup_database(&db).unwrap();
    assert!(backup.exists());
    assert_ne!(backup, db);
    assert_eq!(
        std::fs::metadata(&backup).unwrap().len(),
        std::fs::metadata(&db).unwrap().len()
    );
}
