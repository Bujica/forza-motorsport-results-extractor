//! Rebuild: regenerate globally derived state (best-lap frontier + review
//! cases) from relational data WITHOUT any model call.

use rusqlite::Connection;

use forza_db::repositories::{
    mark_best_laps, query_review_candidates, sync_review_flags, upsert_review_cases,
};

#[derive(Debug, Clone, PartialEq)]
pub struct RebuildOutcome {
    pub corrections_applied: usize,
    pub best_lap_winners: usize,
    pub review_inserted: usize,
    pub review_kept: usize,
    pub review_auto_resolved: usize,
    pub flags_ensured: usize,
    pub flags_resolved: usize,
}

/// Full rebuild pass. Order matters:
/// 1. apply all persisted corrections to lap_records;
/// 2. recompute the frontier over current lap rows;
/// 3. refresh review candidates against the new derived state
///    (operator-resolved cases are preserved by business key).
///
/// All five steps run in one `BEGIN IMMEDIATE` transaction: a failure between
/// the frontier rewrite and the review refresh used to leave a new frontier
/// paired with stale review cases. Inner writers that manage their own txn
/// (`mark_best_laps`) join this outer one instead of nesting.
pub fn rebuild(conn: &Connection, gamertag: &str) -> Result<RebuildOutcome, String> {
    if !conn.is_autocommit() {
        return Err("rebuild requires autocommit (no outer transaction)".to_string());
    }
    conn.execute_batch("BEGIN IMMEDIATE")
        .map_err(|e| e.to_string())?;
    let inner = rebuild_inner(conn, gamertag);
    match inner {
        Ok(outcome) => {
            conn.execute_batch("COMMIT").map_err(|e| e.to_string())?;
            Ok(outcome)
        }
        Err(e) => {
            let _ = conn.execute_batch("ROLLBACK");
            Err(e)
        }
    }
}

fn rebuild_inner(conn: &Connection, gamertag: &str) -> Result<RebuildOutcome, String> {
    let corrections_applied =
        forza_db::repositories::corrections::apply_all(conn).map_err(|e| e.to_string())?;
    let winners = mark_best_laps(conn, Some(gamertag)).map_err(|e| e.to_string())?;
    let candidates = query_review_candidates(conn).map_err(|e| e.to_string())?;
    let (inserted, kept, auto_resolved) =
        upsert_review_cases(conn, &candidates).map_err(|e| e.to_string())?;
    // Every open case owns one active system flag (Python parity); without
    // this the doctor's `open_reviews_missing_active_flag` fails on any DB
    // with open cases while `stale_active_review_flags` passes trivially.
    let (flags_ensured, flags_resolved) = sync_review_flags(conn).map_err(|e| e.to_string())?;

    // Run-level review counters, per run (a bare uncorrelated subquery would
    // stamp every run with the *global* open count, clobbering `complete_run`).
    conn.execute(
        "UPDATE extraction_runs SET review_case_count = (
            SELECT COUNT(*) FROM review_cases rc WHERE rc.status = 'open' AND rc.run_id = extraction_runs.id
        )",
        [],
    )
    .map_err(|e| e.to_string())?;

    Ok(RebuildOutcome {
        corrections_applied,
        best_lap_winners: winners.len(),
        review_inserted: inserted,
        review_kept: kept,
        review_auto_resolved: auto_resolved,
        flags_ensured,
        flags_resolved,
    })
}
