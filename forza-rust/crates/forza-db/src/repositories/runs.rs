//! `extraction_runs` repository plus the run-input/result/attempt graph
//! helpers used by the demo seeder and constraint tests.
//!
//! The run row snapshots the whole LLM/image configuration (hence the many
//! columns); the seeder fills the mandatory subset with the same defaults as
//! the application configuration crate.

use crate::error::DbError;
use rusqlite::{Connection, params};

pub struct RunInsert {
    pub id: String,
    pub status: String,
    pub mode: String,
}

impl RunInsert {
    pub fn demo(id: &str) -> Self {
        Self {
            id: id.to_string(),
            status: "completed".into(),
            mode: "normal".into(),
        }
    }
}

pub fn insert_run(conn: &Connection, run: &RunInsert) -> Result<String, DbError> {
    conn.execute(
        "INSERT INTO extraction_runs
            (id, status, mode, workers, model, input_dir, prompt_name, prompt_hash,
             total_inputs, to_process, created_at)
         VALUES (?1, ?2, ?3, 1, 'seed-model', '.', 'seed', 'seed-hash', 0, 0, datetime('now'))",
        params![run.id, run.status, run.mode],
    )?;
    Ok(run.id.clone())
}

/// Insert a run_input plus its matching extraction_result, returning the
/// generated result id.
pub fn insert_input_and_result(
    conn: &Connection,
    run_id: &str,
    image_file_id: &str,
    decision: &str,
    result_status: &str,
    input_order: i64,
) -> Result<String, DbError> {
    let input_id: i64 = conn.query_row(
        "INSERT INTO run_inputs (id, run_id, image_file_id, decision, input_order, input_path, created_at)
         SELECT COALESCE(MAX(id), 0) + 1, ?1, ?2, ?3, ?4, 'seed/path.png', datetime('now')
         FROM run_inputs RETURNING id",
        params![run_id, image_file_id, decision, input_order],
        |row| row.get(0),
    )?;
    let _ = input_id;
    let result_id = format!("res-{run_id}-{input_order}");
    conn.execute(
        "INSERT INTO extraction_results
            (id, run_id, run_input_id, image_file_id, status, attempt_count, created_at, updated_at)
         VALUES (?1, ?2, ?3, ?4, ?5, 0, datetime('now'), datetime('now'))",
        params![result_id, run_id, input_id, image_file_id, result_status],
    )?;
    Ok(result_id)
}

/// Insert an accepted attempt for a result. The caller must ensure the
/// result's own status is consistent (`ck_attempt_acceptance_status`).
#[allow(clippy::too_many_arguments)]
pub fn insert_accepted_attempt(
    conn: &Connection,
    result_id: &str,
    run_id: &str,
    image_file_id: &str,
) -> Result<String, DbError> {
    let attempt_id = format!("att-{result_id}");
    conn.execute(
        "INSERT INTO extraction_attempts
            (id, extraction_result_id, run_id, image_file_id, attempt_number,
             attempt_reason, status, accepted, created_at)
         SELECT ?1, ?2, ?3, ?4, 1, 'initial', 'ok', 1, datetime('now')
         WHERE EXISTS (SELECT 1 FROM extraction_results r
                       WHERE r.id = ?2 AND r.status IN ('ok', 'error', 'cancelled'))",
        params![attempt_id, result_id, run_id, image_file_id],
    )?;
    Ok(attempt_id)
}
