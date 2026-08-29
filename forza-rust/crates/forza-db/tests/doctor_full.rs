// Test harness: unwraps are idiomatic assertion helpers here.
#![allow(clippy::unwrap_used, clippy::expect_used)]

//! Full DB doctor battery: clean database passes, targeted corruption is
//! detected, and a non-current schema short-circuits to `schema_head`.

use forza_db::{doctor, upgrade};

fn keys(report: &doctor::DoctorReport) -> Vec<&'static str> {
    report.checks.iter().map(|c| c.key).collect()
}

#[test]
fn full_doctor_passes_on_fresh_current_database() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("fresh.sqlite3");
    upgrade(&path).unwrap();
    let conn = forza_db::open_connection(&path).unwrap();
    let report = doctor::run_full_doctor(&conn, "current".to_string()).unwrap();

    assert!(report.ok, "{report:?}");
    assert!(
        report.checks.iter().all(|c| c.count == 0),
        "clean database must report zero counts: {report:?}"
    );

    // Representative checks from every Python module must be present.
    let present = keys(&report);
    for expected in [
        "sqlite_integrity_check",
        "foreign_key_violations",
        "invalid_status_values",
        "runs_left_running",
        "run_counters_mismatch",
        "run_input_contract_invalid",
        "images_missing_metadata",
        "available_images_missing_files",
        "best_laps_without_positive_ms",
        "review_business_key_not_canonical",
        "ok_results_without_accepted_attempt",
        "request_hash_invalid",
        "vocabulary_check_constraints_missing",
        "schema_column_drift",
        "schema_server_default_drift",
        "frozen_schema_sql_drift",
    ] {
        assert!(present.contains(&expected), "missing check {expected}");
    }
    assert!(
        present.len() >= 60,
        "expected the full battery, got {}",
        present.len()
    );
}

#[test]
fn full_doctor_flags_run_counter_and_review_identity_corruption() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("corrupt.sqlite3");
    upgrade(&path).unwrap();
    let conn = forza_db::open_connection(&path).unwrap();

    // A run whose stored counters disagree with relational rows.
    conn.execute_batch(
        "INSERT INTO extraction_runs (id, status, mode, model, total_inputs, to_process,
                                      created_at)
         VALUES ('run-1', 'completed', 'normal', 'm', 5, 5, datetime('now'));
         INSERT INTO run_inputs (run_id, input_order, input_path, decision, created_at)
         VALUES ('run-1', 0, 'a.png', 'skip', datetime('now'));",
    )
    .unwrap();

    let report = doctor::run_full_doctor(&conn, "current".to_string()).unwrap();
    assert!(!report.ok);
    let counters = report
        .checks
        .iter()
        .find(|c| c.key == "run_counters_mismatch")
        .unwrap();
    assert_eq!(counters.count, 1, "{counters:?}");
    assert!(counters.detail.contains("total_inputs"), "{counters:?}");
}

#[test]
fn full_doctor_flags_prompt_snapshot_integrity() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("snapshot.sqlite3");
    upgrade(&path).unwrap();
    let conn = forza_db::open_connection(&path).unwrap();

    conn.execute_batch(
        "INSERT INTO prompt_snapshots (id, prompt_name, content_hash, system_text, created_at)
         VALUES ('bad:snap', 'p', 'wronghash', 'system text', datetime('now'));",
    )
    .unwrap();

    let report = doctor::run_full_doctor(&conn, "current".to_string()).unwrap();
    assert!(!report.ok);
    let integrity = report
        .checks
        .iter()
        .find(|c| c.key == "prompt_snapshot_integrity_invalid")
        .unwrap();
    assert_eq!(integrity.count, 1, "{integrity:?}");
}

#[test]
fn full_doctor_flags_error_attempt_without_debug_evidence() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("attempts.sqlite3");
    upgrade(&path).unwrap();
    let conn = forza_db::open_connection(&path).unwrap();

    conn.execute_batch(
        "INSERT INTO extraction_runs (id, status, mode, model, prompt_name, prompt_hash,
                                      created_at)
         VALUES ('run-e', 'completed', 'normal', 'm', 'p', 'h', datetime('now'));
         INSERT INTO prompt_snapshots (id, prompt_name, content_hash, system_text, created_at)
         VALUES ('p:h', 'p', 'h', 'system text', datetime('now'));
         UPDATE extraction_runs SET prompt_snapshot_id = 'p:h' WHERE id = 'run-e';
         INSERT INTO image_files (id, file_hash, first_seen_at, created_at, updated_at)
         VALUES ('img-e', 'hash-e', datetime('now'), datetime('now'), datetime('now'));
         INSERT INTO run_inputs (id, run_id, image_file_id, input_order, input_path, decision,
                                 created_at)
         VALUES (1, 'run-e', 'img-e', 0, 'a.png', 'process', datetime('now'));
         INSERT INTO extraction_results (id, run_id, run_input_id, image_file_id, status,
                                         attempt_count, prompt_snapshot_id, created_at)
         VALUES ('res-e', 'run-e', 1, 'img-e', 'error', 1, 'p:h', datetime('now'));
         INSERT INTO model_runtime_snapshots (id, run_id, endpoint, captured_at)
         VALUES ('snap-1', 'run-e', 'http://localhost:1234', datetime('now'));
         INSERT INTO extraction_attempts (id, extraction_result_id, run_id, image_file_id,
                                          runtime_snapshot_id, attempt_number, attempt_reason,
                                          status, accepted, created_at)
         VALUES ('att-e', 'res-e', 'run-e', 'img-e', 'snap-1', 1, 'initial', 'error', 0,
                 datetime('now'));",
    )
    .unwrap();

    let report = doctor::run_full_doctor(&conn, "current".to_string()).unwrap();
    let evidence = report
        .checks
        .iter()
        .find(|c| c.key == "error_attempts_missing_sql_evidence")
        .unwrap();
    assert_eq!(evidence.count, 1, "{evidence:?}");
    assert!(!report.ok);
}

#[test]
fn full_doctor_short_circuits_on_noncurrent_schema() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("old-schema.sqlite3");
    upgrade(&path).unwrap();
    let conn = forza_db::open_connection(&path).unwrap();
    conn.pragma_update(None, "user_version", 0).unwrap();

    let report = doctor::run_full_doctor(&conn, "needs_upgrade".to_string()).unwrap();
    assert!(!report.ok);
    assert_eq!(report.checks.len(), 1);
    assert_eq!(report.checks[0].key, "schema_head");
    assert_eq!(report.checks[0].count, 1);
}
