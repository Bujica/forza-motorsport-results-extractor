// Test harness: unwraps are idiomatic assertion helpers here.
#![allow(clippy::unwrap_used, clippy::expect_used)]

//! Basic DB doctor battery on a healthy seeded database and an empty one.

use forza_db::{doctor, upgrade};

#[test]
fn doctor_reports_ok_on_current_seeded_database() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("doctor.sqlite3");
    upgrade(&path).unwrap();
    {
        let mut conn = forza_db::open_connection(&path).unwrap();
        forza_db::test_support::seed_demo_database(&mut conn).unwrap();
    }
    let report = doctor::doctor_on_path(&path).unwrap();
    assert!(report.ok, "{report:?}");
    assert_eq!(report.schema_status, "current");
    assert_eq!(report.user_version, forza_db::SCHEMA_VERSION);
    assert!(report.checks.iter().all(|c| c.ok), "{report:?}");
}

#[test]
fn doctor_reports_empty_for_missing_file() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("nothing-here.sqlite3");
    let report = doctor::doctor_on_path(&path).unwrap();
    assert!(!report.ok);
    assert_eq!(report.schema_status, "empty");
}

#[test]
fn doctor_detects_foreign_key_violations_when_keys_off_writes_happen() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("violations.sqlite3");
    upgrade(&path).unwrap();
    {
        // Write a dangling row bypassing FK enforcement to simulate corruption.
        let raw = rusqlite::Connection::open(&path).unwrap();
        raw.pragma_update(None, "foreign_keys", "OFF").unwrap();
        raw.execute_batch(
            "INSERT INTO extraction_runs (id, status, mode, model, created_at) VALUES ('ghost', 'pending', 'normal', 'm', datetime('now'));
             INSERT INTO lap_records (id, run_id, image_file_id, extraction_result_id, lap_index,
                                      driver, car, race_class, track, weather, best_lap_ms, dirty, created_at)
             VALUES ('bad-lap', 'ghost', 'no-image', 'no-result', 0,
                     'd', 'c', 'A', 'T', 'dry', 90000, 0, datetime('now'));",
        )
        .unwrap();
    }
    let report = doctor::doctor_on_path(&path).unwrap();
    assert!(!report.ok);
    assert!(
        report
            .checks
            .iter()
            .any(|c| c.key == "foreign_key_check" && !c.ok),
        "{report:?}"
    );
}
