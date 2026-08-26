//! Rebuild: regenerate globally derived state (best-lap frontier + review
//! cases) from relational data WITHOUT any model call.

use rusqlite::Connection;

use forza_db::repositories::{mark_best_laps, query_review_candidates, upsert_review_cases};

#[derive(Debug, Clone, PartialEq)]
pub struct RebuildOutcome {
    pub best_lap_winners: usize,
    pub review_inserted: usize,
    pub review_kept: usize,
    pub review_auto_resolved: usize,
}

/// Full rebuild pass. Order matters:
/// 1. recompute the frontier over current lap rows;
/// 2. refresh review candidates against the new derived state
///    (operator-resolved cases are preserved by business key).
pub fn rebuild(conn: &Connection, gamertag: &str) -> Result<RebuildOutcome, String> {
    let winners = mark_best_laps(conn, Some(gamertag)).map_err(|e| e.to_string())?;
    let candidates = query_review_candidates(conn).map_err(|e| e.to_string())?;
    let (inserted, kept, auto_resolved) =
        upsert_review_cases(conn, &candidates).map_err(|e| e.to_string())?;

    // Run-level review counters.
    conn.execute_batch(
        "UPDATE extraction_runs SET review_case_count=
            (SELECT COUNT(*) FROM review_cases WHERE status='open');",
    )
    .map_err(|e| e.to_string())?;

    Ok(RebuildOutcome {
        best_lap_winners: winners.len(),
        review_inserted: inserted,
        review_kept: kept,
        review_auto_resolved: auto_resolved,
    })
}
