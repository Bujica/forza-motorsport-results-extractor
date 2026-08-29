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
fn full_doctor_accepts_stamped_evidence_chain() {
    // Mirrors what the extraction runner now persists: attempts reference the
    // preflight runtime snapshot, carry a canonical request_hash, and results
    // retain the run's prompt snapshot.
    use forza_db::repositories::runs::{AttemptInsert, insert_attempt_full};

    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("chain.sqlite3");
    upgrade(&path).unwrap();
    let conn = forza_db::open_connection(&path).unwrap();

    // Prompt snapshot with correct integrity (id = name:payload_hash).
    let system_text = "system prompt";
    let payload = format!(
        "{{\"response_schema_json\":null,\"system_text\":{},\"user_text_template\":null}}",
        serde_json::to_string(system_text).unwrap()
    );
    use sha2::{Digest, Sha256};
    let payload_hash = format!("{:x}", Sha256::digest(payload.as_bytes()));
    let prompt_id = format!("prompt:{payload_hash}");
    conn.execute_batch(&format!(
        "INSERT INTO prompt_snapshots (id, prompt_name, content_hash, system_text, created_at)
         VALUES ('{prompt_id}', 'prompt', '{payload_hash}', 'system prompt', datetime('now'));
         INSERT INTO extraction_runs (id, status, mode, model, prompt_name, prompt_hash,
                                      prompt_snapshot_id, total_inputs, to_process, processed, succeeded,
                                      created_at)
         VALUES ('run-1', 'completed', 'normal', 'model-x', 'prompt', '{payload_hash}',
                 '{prompt_id}', 1, 1, 1, 1, datetime('now'));
         INSERT INTO model_runtime_snapshots (id, run_id, snapshot_kind, endpoint, captured_at)
         VALUES ('runtime-run-1-preflight', 'run-1', 'preflight', 'http://localhost:1234',
                 datetime('now'));
         INSERT INTO image_files (id, file_hash, file_status, size_bytes, width_px, height_px,
                                  first_seen_at, created_at, updated_at)
         VALUES ('img-1', 'hash_1', 'missing', 100, 100, 80,
                 datetime('now'), datetime('now'), datetime('now'));
         INSERT INTO run_inputs (id, run_id, image_file_id, input_order, input_path, decision,
                                 created_at)
         VALUES (1, 'run-1', 'img-1', 0, 'shot.png', 'process', datetime('now'));
         INSERT INTO extraction_results (id, run_id, run_input_id, image_file_id, status,
                                         attempt_count, prompt_snapshot_id, created_at)
         VALUES ('res-1', 'run-1', 1, 'img-1', 'ok', 1, '{prompt_id}', datetime('now'));"
    ))
    .unwrap();

    let messages = r#"[{"role":"user","content":"redacted"}]"#;
    let request_hash = forza_db::evidence::canonical_request_hash(
        Some(messages),
        Some(r#"{"temperature":0.7}"#),
        Some(&prompt_id),
        Some("model-x"),
        Some("hash_1"),
        Some("png"),
        Some("image/png"),
        Some(1600),
        Some(900),
        Some(2048),
    );
    let insert = AttemptInsert {
        attempt_number: 1,
        attempt_reason: "initial",
        status: "ok",
        accepted: true,
        rejected_reason: None,
        model: Some("model-x"),
        model_instance_id: None,
        http_status: None,
        error_code: None,
        error_message: None,
        request_image_format: Some("png"),
        request_image_mime_type: Some("image/png"),
        request_image_width: Some(1600),
        request_image_height: Some(900),
        request_image_bytes: Some(2048),
        context_length: Some(5000),
        reasoning_mode: Some("off"),
        request_config_json: Some(r#"{"temperature":0.7}"#),
        request_messages_json: Some(messages),
        request_hash: Some(&request_hash),
        runtime_snapshot_id: Some("runtime-run-1-preflight"),
        retry_instruction_text: None,
        raw_response: Some("raw model output"),
        parsed_json: None,
        parse_error: None,
        validation_status: None,
        validation_issues_json: None,
        response_stats_json: None,
        duration_ms: 100,
        input_tokens: None,
        output_tokens: None,
        reasoning_tokens: None,
        total_tokens: None,
        tokens_per_second: None,
        time_to_first_token_s: None,
        model_load_time_s: None,
    };
    insert_attempt_full(&conn, "run-1", "img-1", "res-1", &insert).unwrap();
    conn.execute(
        "UPDATE extraction_results SET accepted_attempt_id='att-res-1-1' WHERE id='res-1'",
        [],
    )
    .unwrap();

    let report = doctor::run_full_doctor(&conn, "current".to_string()).unwrap();
    for key in [
        "attempts_missing_runtime_snapshot",
        "request_hash_invalid",
        "result_prompt_mismatch",
        "runs_missing_prompt_snapshot",
        "prompt_snapshot_integrity_invalid",
        "run_prompt_snapshot_mismatch",
        "attempt_runtime_parent_mismatch",
        "accepted_attempts_missing_raw_evidence",
        "run_counters_mismatch",
    ] {
        let check = report.checks.iter().find(|c| c.key == key).unwrap();
        assert_eq!(check.count, 0, "{key} must pass: {check:?}");
    }
    assert!(report.ok, "{report:?}");
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
