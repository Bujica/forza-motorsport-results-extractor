// Outcome filter labels map to lifecycle truth: the stored outcome
// vocabulary has no system-resolved value, so `auto_resolved` rows keep
// `outcome='pending'` and both labels filter by status.
#![allow(clippy::unwrap_used, clippy::expect_used)]

use forza_app::services::review_queue::{ReviewQueueFilter, list_review_cases};

fn seed_db(path: &std::path::Path) -> rusqlite::Connection {
    forza_db::upgrade(path).unwrap();
    let conn = forza_db::open_connection(path).unwrap();
    conn.execute_batch(
        "INSERT INTO review_cases
           (id, business_key, case_number, reason, status, outcome, created_at)
         VALUES ('case-1', 'k-open', 1, 'car', 'open', 'pending', datetime('now')),
                ('case-2', 'k-auto', 2, 'car', 'auto_resolved', 'pending', datetime('now')),
                ('case-3', 'k-conf', 3, 'car', 'resolved', 'confirmed', datetime('now'));",
    )
    .unwrap();
    conn
}

fn filtered(conn: &rusqlite::Connection, bucket: &str, outcome: &str) -> Vec<i64> {
    let mut rows = list_review_cases(
        conn,
        &ReviewQueueFilter {
            bucket: bucket.to_string(),
            reason: None,
            outcome: Some(outcome.to_string()),
            run_id: None,
            image_file_id: None,
        },
    )
    .unwrap()
    .into_iter()
    .map(|c| c.case_number)
    .collect::<Vec<_>>();
    rows.sort_unstable();
    rows
}

#[test]
fn outcome_filter_maps_lifecycle_labels() {
    let dir = tempfile::tempdir().unwrap();
    let conn = seed_db(&dir.path().join("outcome.sqlite3"));

    assert_eq!(filtered(&conn, "all", "auto_resolved"), vec![2]);
    assert_eq!(filtered(&conn, "resolved", "auto_resolved"), vec![2]);
    assert_eq!(filtered(&conn, "all", "pending"), vec![1]);
    assert_eq!(filtered(&conn, "open", "pending"), vec![1]);
    assert_eq!(filtered(&conn, "all", "confirmed"), vec![3]);
    assert_eq!(filtered(&conn, "open", "auto_resolved"), Vec::<i64>::new());
}
