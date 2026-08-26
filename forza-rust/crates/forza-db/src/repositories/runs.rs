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

/// Run input for an actually-processed image: real source path plus the
/// Python `process_reason` vocabulary ("full_run" | "force" |
/// "retry_errors"), with the pending result row.
pub fn insert_processed_input(
    conn: &Connection,
    run_id: &str,
    image_file_id: &str,
    input_path: &str,
    process_reason: &str,
    input_order: i64,
) -> Result<String, DbError> {
    let input_id: i64 = conn.query_row(
        "INSERT INTO run_inputs (id, run_id, image_file_id, decision, input_order,
                                 input_path, process_reason, created_at)
         SELECT COALESCE(MAX(id), 0) + 1, ?1, ?2, 'process', ?3, ?4, ?5, datetime('now')
         FROM run_inputs RETURNING id",
        params![
            run_id,
            image_file_id,
            input_order,
            input_path,
            process_reason
        ],
        |row| row.get(0),
    )?;
    let _ = input_id;
    let result_id = format!("res-{run_id}-{input_order}");
    conn.execute(
        "INSERT INTO extraction_results
            (id, run_id, run_input_id, image_file_id, status, attempt_count, created_at, updated_at)
         VALUES (?1, ?2, ?3, ?4, 'running', 0, datetime('now'), datetime('now'))",
        params![result_id, run_id, input_id, image_file_id],
    )?;
    Ok(result_id)
}

/// Primitive attempt row for persistence — converted from the backend's
/// typed record by the application layer (no crate dependency inversion).
pub struct AttemptInsert<'a> {
    pub attempt_number: i64,
    pub attempt_reason: &'a str,
    pub status: &'a str,
    pub accepted: bool,
    pub rejected_reason: Option<&'a str>,
    pub model: Option<&'a str>,
    pub model_instance_id: Option<&'a str>,
    pub http_status: Option<i64>,
    pub error_code: Option<&'a str>,
    pub error_message: Option<&'a str>,
    pub request_image_format: Option<&'a str>,
    pub request_image_mime_type: Option<&'a str>,
    pub request_image_width: Option<i64>,
    pub request_image_height: Option<i64>,
    pub request_image_bytes: Option<i64>,
    pub context_length: Option<i64>,
    pub reasoning_mode: Option<&'a str>,
    pub request_config_json: Option<&'a str>,
    pub request_messages_json: Option<&'a str>,
    pub request_hash: Option<&'a str>,
    pub retry_instruction_text: Option<&'a str>,
    pub raw_response: Option<&'a str>,
    pub parsed_json: Option<&'a str>,
    pub parse_error: Option<&'a str>,
    pub validation_status: Option<&'a str>,
    pub validation_issues_json: Option<&'a str>,
    pub response_stats_json: Option<&'a str>,
    pub duration_ms: i64,
    pub input_tokens: Option<i64>,
    pub output_tokens: Option<i64>,
    pub reasoning_tokens: Option<i64>,
    pub total_tokens: Option<i64>,
    pub tokens_per_second: Option<f64>,
    pub time_to_first_token_s: Option<f64>,
    pub model_load_time_s: Option<f64>,
}

/// Insert an extraction attempt with the full evidence payload
/// (raw/parsed/config/messages/stats) as persisted by the pipeline.
pub fn insert_attempt_full(
    conn: &Connection,
    run_id: &str,
    image_file_id: &str,
    extraction_result_id: &str,
    record: &AttemptInsert<'_>,
) -> Result<String, DbError> {
    let id = format!("att-{extraction_result_id}-{}", record.attempt_number);
    conn.execute(
        "INSERT INTO extraction_attempts
            (id, extraction_result_id, run_id, image_file_id, attempt_number,
             attempt_reason, status, accepted, rejected_reason,
             http_status, error_code, error_message,
             model, model_instance_id,
             request_image_format, request_image_mime_type,
             request_image_width, request_image_height, request_image_bytes,
             context_length, reasoning_mode,
             request_config_json, request_messages_json, request_hash,
             retry_instruction_text,
             raw_response, parsed_json, parse_error,
             validation_status, validation_issues_json, response_stats_json,
             input_tokens, output_tokens, reasoning_tokens, total_tokens,
             duration_ms, tokens_per_second, time_to_first_token_s,
             model_load_time_s, created_at)
         VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,
                 ?18,?19,?20,?21,?22,?23,?24,?25,?26,?27,?28,?29,?30,?31,
                 ?32,?33,?34,?35,?36,?37,?38,?39,datetime('now'))",
        params![
            id,
            extraction_result_id,
            run_id,
            image_file_id,
            record.attempt_number,
            record.attempt_reason,
            record.status,
            if record.accepted { 1 } else { 0 },
            record.rejected_reason,
            record.http_status,
            record.error_code,
            record.error_message,
            record.model,
            record.model_instance_id,
            record.request_image_format,
            record.request_image_mime_type,
            record.request_image_width,
            record.request_image_height,
            record.request_image_bytes,
            record.context_length,
            record.reasoning_mode,
            record.request_config_json,
            record.request_messages_json,
            record.request_hash,
            record.retry_instruction_text,
            record.raw_response,
            record.parsed_json,
            record.parse_error,
            record.validation_status,
            record.validation_issues_json,
            record.response_stats_json,
            record.input_tokens,
            record.output_tokens,
            record.reasoning_tokens,
            record.total_tokens,
            record.duration_ms,
            record.tokens_per_second,
            record.time_to_first_token_s,
            record.model_load_time_s,
        ],
    )?;
    Ok(id)
}

/// Mark a result as ok and link its accepted attempt.
#[allow(clippy::too_many_arguments)]
pub fn finalize_result_ok(
    conn: &Connection,
    result_id: &str,
    accepted_attempt_row_id: &str,
    attempt_count: i64,
    stats: &ResultStats<'_>,
) -> Result<(), DbError> {
    conn.execute(
        "UPDATE extraction_results SET
            status='ok', accepted_attempt_id=?2, attempt_count=?3,
            model=COALESCE(?4, model), model_instance_id=COALESCE(?5, model_instance_id),
            input_tokens=?6, output_tokens=?7, reasoning_tokens=?8, total_tokens=?9,
            tokens_per_second=?10, time_to_first_token_s=?11, model_load_time_s=?12,
            duration_ms=?13, updated_at=datetime('now')
         WHERE id=?1",
        params![
            result_id,
            accepted_attempt_row_id,
            attempt_count,
            stats.model,
            stats.model_instance_id,
            stats.input_tokens,
            stats.output_tokens,
            stats.reasoning_tokens,
            stats.total_tokens,
            stats.tokens_per_second,
            stats.time_to_first_token_s,
            stats.model_load_time_s,
            stats.duration_ms,
        ],
    )?;
    Ok(())
}

pub struct ResultStats<'a> {
    pub model: Option<&'a str>,
    pub model_instance_id: Option<&'a str>,
    pub input_tokens: Option<i64>,
    pub output_tokens: Option<i64>,
    pub reasoning_tokens: Option<i64>,
    pub total_tokens: Option<i64>,
    pub tokens_per_second: Option<f64>,
    pub time_to_first_token_s: Option<f64>,
    pub model_load_time_s: Option<f64>,
    pub duration_ms: i64,
}

/// Insert a standalone run_input row (skip/duplicate/missing decisions —
/// no extraction_result attached).
pub fn insert_run_input_only(
    conn: &Connection,
    run_id: &str,
    image_file_id: Option<&str>,
    decision: &str,
    input_order: i64,
    input_path: &str,
) -> Result<i64, DbError> {
    conn.execute(
        "INSERT INTO run_inputs (run_id, image_file_id, decision, input_order, input_path, created_at)
         SELECT COALESCE(MAX(id), 0) + 1, ?1, ?2, ?3, ?4, datetime('now') FROM run_inputs",
        params![run_id, image_file_id, decision, input_order, input_path],
    )?;
    Ok(conn.last_insert_rowid())
}

/// Transition a run to running.
pub fn mark_run_running(conn: &Connection, run_id: &str) -> Result<(), DbError> {
    conn.execute(
        "UPDATE extraction_runs SET status='running', started_at=datetime('now') WHERE id=?1",
        params![run_id],
    )?;
    Ok(())
}

/// Finalize a run with outcome counters.
#[allow(clippy::too_many_arguments)]
pub fn complete_run(
    conn: &Connection,
    run_id: &str,
    status: &str,
    total_inputs: i64,
    processed: i64,
    succeeded: i64,
    failed: i64,
    skipped: i64,
    duplicate_count: i64,
) -> Result<(), DbError> {
    conn.execute(
        "UPDATE extraction_runs SET status=?2, finished_at=datetime('now'),
            total_inputs=?3, to_process=?3, processed=?4, succeeded=?5,
            failed=?6, skipped=?7, duplicate_count=?8
         WHERE id=?1",
        params![
            run_id,
            status,
            total_inputs,
            processed,
            succeeded,
            failed,
            skipped,
            duplicate_count
        ],
    )?;
    Ok(())
}

/// Find an available image row by content hash, if any.
pub fn find_image_id_by_hash(
    conn: &Connection,
    file_hash: &str,
) -> Result<Option<String>, DbError> {
    let id = conn
        .query_row(
            "SELECT id FROM image_files WHERE file_hash=?1 AND file_status='available' LIMIT 1",
            params![file_hash],
            |r| r.get::<_, String>(0),
        )
        .ok();
    Ok(id)
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
