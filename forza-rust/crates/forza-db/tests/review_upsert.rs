// Test harness: unwraps are idiomatic assertion helpers here.
#![allow(clippy::unwrap_used, clippy::expect_used)]

//! Auto-resolve keeps `outcome='pending'` by design (the outcome vocabulary
//! has no system-resolved value, CHECK-enforced on both stacks): only
//! `status` flips, plus `resolved_at`/`resolution_note` (Python parity).

use forza_db::repositories::reviews::upsert_review_cases;
use forza_db::{open_connection, upgrade};

#[test]
fn auto_resolve_flips_status_and_stamps_resolution() {
    let dir = tempfile::tempdir().unwrap();
    let db = dir.path().join("review_upsert.sqlite3");
    upgrade(&db).unwrap();
    let conn = open_connection(&db).unwrap();
    conn.execute_batch(
        "INSERT INTO review_cases
           (id, business_key, case_number, reason, status, outcome, created_at)
         VALUES ('case-1', 'car:img-1:0', 1, 'car', 'open', 'pending', datetime('now'));",
    )
    .unwrap();

    let (inserted, kept, auto_resolved) = upsert_review_cases(&conn, &[]).unwrap();
    assert_eq!((inserted, kept, auto_resolved), (0, 0, 1));

    let (status, outcome, resolved_at, note): (String, String, Option<String>, Option<String>) =
        conn.query_row(
            "SELECT status, outcome, CAST(resolved_at AS TEXT), resolution_note
             FROM review_cases WHERE business_key = 'car:img-1:0'",
            [],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
        )
        .unwrap();
    assert_eq!(status, "auto_resolved");
    // No system-resolved outcome exists in the CHECK vocabulary: the GUI maps
    // this for display (`display_outcome`) instead of persisting a new value.
    assert_eq!(outcome, "pending");
    assert!(resolved_at.is_some());
    assert_eq!(note.as_deref(), Some("no_longer_detected"));
}

#[test]
fn returning_condition_reopens_auto_resolved_case() {
    use forza_db::repositories::reviews::{LapCandidateRow, ReviewCandidate};

    let dir = tempfile::tempdir().unwrap();
    let db = dir.path().join("review_reopen.sqlite3");
    upgrade(&db).unwrap();
    let conn = open_connection(&db).unwrap();
    conn.execute_batch(
        "INSERT INTO image_files (id, file_hash, first_seen_at, created_at, updated_at)
         VALUES ('img-9', 'h9', datetime('now'), datetime('now'), datetime('now'));
         INSERT INTO extraction_runs (id, status, mode, model, created_at)
         VALUES ('run-9', 'completed', 'normal', 'm', datetime('now'));
         INSERT INTO run_inputs (id, run_id, input_order, input_path, decision, created_at)
         VALUES (1, 'run-9', 0, 'nine.png', 'process', datetime('now'));
         INSERT INTO extraction_results (id, run_id, run_input_id, image_file_id, status, created_at)
         VALUES ('res-9', 'run-9', 1, 'img-9', 'ok', datetime('now'));
         INSERT INTO lap_records (id, run_id, image_file_id, extraction_result_id, lap_index, created_at)
         VALUES ('lap-9', 'run-9', 'img-9', 'res-9', 0, datetime('now'));
         INSERT INTO review_cases
           (id, business_key, case_number, reason, status, outcome, model_value,
            resolved_at, resolution_note, created_at)
         VALUES ('case-1', 'car:img-9:0', 1, 'car', 'auto_resolved', 'pending',
                 'Old Value', datetime('now'), 'no_longer_detected', datetime('now'));",
    )
    .unwrap();

    let candidate = ReviewCandidate {
        reason: "car",
        trigger: "car_not_in_reference",
        model_value: "New Value".to_string(),
        per_image: false,
        row: LapCandidateRow {
            lap_id: "lap-9".to_string(),
            image_file_id: "img-9".to_string(),
            lap_index: 0,
            driver: "d".to_string(),
            source_file: None,
            best_lap: None,
            track: "t".to_string(),
            weather: "dry".to_string(),
            race_class: "A".to_string(),
            car: "c".to_string(),
            dirty: false,
            is_best_lap: false,
        },
    };
    let (inserted, kept, auto_resolved) = upsert_review_cases(&conn, &[candidate]).unwrap();
    assert_eq!((inserted, kept, auto_resolved), (0, 1, 0));

    let (status, outcome, model_value, lap_id, resolved_at): (
        String,
        String,
        String,
        Option<String>,
        Option<String>,
    ) = conn
        .query_row(
            "SELECT status, outcome, model_value, lap_record_id, CAST(resolved_at AS TEXT)
             FROM review_cases WHERE business_key = 'car:img-9:0'",
            [],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?)),
        )
        .unwrap();
    assert_eq!(status, "open");
    assert_eq!(outcome, "pending");
    assert_eq!(model_value, "New Value");
    assert_eq!(lap_id.as_deref(), Some("lap-9"));
    assert!(resolved_at.is_none());
}
