// Test harness: unwraps are idiomatic assertion helpers here.
#![allow(clippy::unwrap_used, clippy::expect_used)]

//! Decide classifies the outcome by comparing the operator value against the
//! stored model value (normalized): equal → `confirmed`, different →
//! `model_error` with an `error_type` classification and a `decision:` note.

use forza_db::repositories::corrections::apply_manual_correction;
use forza_db::{open_connection, upgrade};

fn seed_case(conn: &rusqlite::Connection, n: i64, reason: &str, model_value: &str) {
    conn.execute(
        "INSERT INTO image_files (id, file_hash, first_seen_at, created_at, updated_at)
         VALUES ('img-seed', 'h', datetime('now'), datetime('now'), datetime('now'))
         ON CONFLICT(id) DO NOTHING",
        [],
    )
    .unwrap();
    conn.execute(
        "INSERT INTO review_cases
           (id, business_key, case_number, reason, status, outcome, model_value,
            image_file_id, created_at)
         VALUES (?1, ?2, ?3, ?4, 'open', 'pending', ?5, 'img-seed', datetime('now'))",
        rusqlite::params![
            format!("case-{n}"),
            format!("key-{n}"),
            n,
            reason,
            model_value
        ],
    )
    .unwrap();
}

fn read_case(
    conn: &rusqlite::Connection,
    n: i64,
) -> (String, String, Option<String>, Option<String>) {
    conn.query_row(
        "SELECT status, outcome, error_type, resolution_note FROM review_cases WHERE case_number=?1",
        [n],
        |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
    )
    .unwrap()
}

#[test]
fn confirming_model_value_records_confirmed() {
    let dir = tempfile::tempdir().unwrap();
    let db = dir.path().join("decide_confirm.sqlite3");
    upgrade(&db).unwrap();
    let conn = open_connection(&db).unwrap();
    seed_case(&conn, 1, "car", "Toyota Supra");

    apply_manual_correction(&conn, 1, "car", "toyota supra", None).unwrap();

    let (status, outcome, error_type, note) = read_case(&conn, 1);
    assert_eq!(status, "resolved");
    assert_eq!(outcome, "confirmed");
    assert_eq!(error_type, None);
    assert_eq!(note.as_deref(), Some("decision:car=toyota supra"));
}

#[test]
fn correcting_model_value_records_model_error_with_taxonomy() {
    let dir = tempfile::tempdir().unwrap();
    let db = dir.path().join("decide_correct.sqlite3");
    upgrade(&db).unwrap();
    let conn = open_connection(&db).unwrap();
    seed_case(&conn, 1, "car", "Honda Civic");
    seed_case(&conn, 2, "dirty_lap", "true");

    apply_manual_correction(&conn, 1, "car", "Toyota Supra", None).unwrap();
    let (status, outcome, error_type, note) = read_case(&conn, 1);
    assert_eq!(
        (status.as_str(), outcome.as_str()),
        ("resolved", "model_error")
    );
    assert_eq!(error_type.as_deref(), Some("car_wrong"));
    assert_eq!(note.as_deref(), Some("decision:car=Toyota Supra"));

    apply_manual_correction(&conn, 2, "dirty", "false", None).unwrap();
    let (_, outcome, error_type, _) = read_case(&conn, 2);
    assert_eq!(outcome, "model_error");
    assert_eq!(error_type.as_deref(), Some("dirty_lap_false_positive"));
}
