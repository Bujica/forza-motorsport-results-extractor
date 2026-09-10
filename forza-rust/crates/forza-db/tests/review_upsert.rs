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
