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

/// Runtime/configuration metadata captured on a real extraction run.
///
/// `RunInsert::demo` intentionally remains minimal for low-level tests; live
/// callers must apply this snapshot immediately after creating the run.
pub struct RunMetadata<'a> {
    pub backend: &'a str,
    pub model: &'a str,
    pub input_dir: &'a str,
    pub prompt_name: &'a str,
    pub prompt_hash: Option<&'a str>,
    pub workers: i64,
    pub image_format: &'a str,
    pub max_width: i64,
    pub encode_quality: i64,
    pub grayscale: bool,
    pub context_length: i64,
    pub reasoning_mode: Option<&'a str>,
    pub max_completion_tokens: i64,
    pub temperature: f64,
    pub max_retries: i64,
    pub timeout_connect: i64,
    pub timeout_read: i64,
    /// Free-form provenance JSON (the Rust pipeline stamps the app version).
    pub config_extra_json: Option<&'a str>,
}

pub struct RuntimeSnapshotInsert<'a> {
    pub endpoint: &'a str,
    pub configured_model: &'a str,
    pub matched_model: Option<&'a str>,
    pub loaded_model: Option<&'a str>,
    pub instance_id: Option<&'a str>,
    pub display_name: Option<&'a str>,
    pub publisher: Option<&'a str>,
    pub architecture: Option<&'a str>,
    pub format: Option<&'a str>,
    pub params_string: Option<&'a str>,
    pub quantization: Option<&'a str>,
    pub selected_variant: Option<&'a str>,
    pub size_bytes: Option<i64>,
    pub max_context_length: Option<i64>,
    pub capabilities_json: Option<&'a str>,
    pub desired_load_config_json: &'a str,
    pub effective_load_config_json: Option<&'a str>,
    pub health_ok: bool,
    pub health_message: &'a str,
    pub model_matches_config: Option<bool>,
}

/// Insert an immutable prompt snapshot and return its deterministic identity.
/// Reusing an existing identical snapshot is allowed; changing the payload
/// under the same identity is rejected by the unique key and the caller's
/// deterministic hash.
pub fn insert_prompt_snapshot(
    conn: &Connection,
    id: &str,
    prompt_name: &str,
    content_hash: &str,
    system_text: &str,
) -> Result<String, DbError> {
    conn.execute(
        "INSERT INTO prompt_snapshots
            (id, prompt_name, version_label, content_hash, system_text,
             user_text_template, response_schema_json, created_at)
         VALUES (?1, ?2, 'embedded', ?3, ?4, NULL, NULL, datetime('now'))
         ON CONFLICT(prompt_name, content_hash) DO NOTHING",
        params![id, prompt_name, content_hash, system_text],
    )?;
    Ok(id.to_string())
}

pub fn link_run_prompt_snapshot(
    conn: &Connection,
    run_id: &str,
    snapshot_id: &str,
    prompt_hash: &str,
) -> Result<(), DbError> {
    conn.execute(
        "UPDATE extraction_runs SET prompt_snapshot_id=?2, prompt_hash=?3 WHERE id=?1",
        params![run_id, snapshot_id, prompt_hash],
    )?;
    Ok(())
}

pub fn insert_runtime_snapshot(
    conn: &Connection,
    run_id: &str,
    snapshot_id: &str,
    snapshot: &RuntimeSnapshotInsert<'_>,
) -> Result<(), DbError> {
    conn.execute(
        "INSERT INTO model_runtime_snapshots
            (id, run_id, snapshot_kind, endpoint, configured_model, matched_model,
             loaded_model, instance_id, display_name, publisher, architecture,
             format, params_string, quantization, selected_variant, size_bytes,
             max_context_length, capabilities_json, desired_load_config_json,
             effective_load_config_json, health_ok, health_message,
             model_matches_config, captured_at)
         VALUES (?1, ?2, 'preflight', ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11,
                 ?12, ?13, ?14, ?15, ?16, ?17, ?18, ?19, ?20, ?21, ?22,
                 datetime('now'))",
        params![
            snapshot_id,
            run_id,
            snapshot.endpoint,
            snapshot.configured_model,
            snapshot.matched_model,
            snapshot.loaded_model,
            snapshot.instance_id,
            snapshot.display_name,
            snapshot.publisher,
            snapshot.architecture,
            snapshot.format,
            snapshot.params_string,
            snapshot.quantization,
            snapshot.selected_variant,
            snapshot.size_bytes,
            snapshot.max_context_length,
            snapshot.capabilities_json,
            snapshot.desired_load_config_json,
            snapshot.effective_load_config_json,
            if snapshot.health_ok { 1 } else { 0 },
            snapshot.health_message,
            snapshot.model_matches_config,
        ],
    )?;
    Ok(())
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

/// Fill the live run header from the actual application configuration.
pub fn update_run_metadata(
    conn: &Connection,
    run_id: &str,
    metadata: &RunMetadata<'_>,
) -> Result<(), DbError> {
    conn.execute(
        "UPDATE extraction_runs SET
            backend=?2, model=?3, input_dir=?4, prompt_name=?5, prompt_hash=?6,
            workers=?7, image_format=?8, max_width=?9, encode_quality=?10,
            grayscale=?11, context_length=?12, reasoning_mode=?13,
            max_completion_tokens=?14, temperature=?15, max_retries=?16,
            timeout_connect=?17, timeout_read=?18, config_extra_json=?19
         WHERE id=?1",
        params![
            run_id,
            metadata.backend,
            metadata.model,
            metadata.input_dir,
            metadata.prompt_name,
            metadata.prompt_hash,
            metadata.workers,
            metadata.image_format,
            metadata.max_width,
            metadata.encode_quality,
            if metadata.grayscale { 1 } else { 0 },
            metadata.context_length,
            metadata.reasoning_mode,
            metadata.max_completion_tokens,
            metadata.temperature,
            metadata.max_retries,
            metadata.timeout_connect,
            metadata.timeout_read,
            metadata.config_extra_json,
        ],
    )?;
    Ok(())
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
    let result_id = format!("res-{run_id}-{input_id}");
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
    let result_id = format!("res-{run_id}-{input_id}");
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
    pub runtime_snapshot_id: Option<&'a str>,
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
             runtime_snapshot_id, retry_instruction_text,
             raw_response, parsed_json, parse_error,
             validation_status, validation_issues_json, response_stats_json,
             input_tokens, output_tokens, reasoning_tokens, total_tokens,
             duration_ms, tokens_per_second, time_to_first_token_s,
             model_load_time_s, created_at)
         VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,
                 ?18,?19,?20,?21,?22,?23,?24,?25,?26,?27,?28,?29,?30,?31,
                 ?32,?33,?34,?35,?36,?37,?38,?39,?40,datetime('now'))",
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
            record.runtime_snapshot_id,
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
        "INSERT INTO run_inputs (id, run_id, image_file_id, decision, input_order, input_path, created_at)
         SELECT COALESCE(MAX(id), 0) + 1, ?1, ?2, ?3, ?4, ?5, datetime('now') FROM run_inputs",
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
/// Finalize a run and recompute every stored counter from the relational
/// rows (Python  semantics): run_inputs decisions for the input
/// counters, extraction_results statuses for the result counters, and open
/// review cases for .
pub fn complete_run(conn: &Connection, run_id: &str, status: &str) -> Result<(), DbError> {
    conn.execute(
        "UPDATE extraction_runs SET
            status=?2,
            finished_at=datetime('now'),
            total_inputs = (SELECT COUNT(*) FROM run_inputs WHERE run_id=?1),
            to_process = (SELECT COUNT(*) FROM run_inputs WHERE run_id=?1 AND decision='process'),
            skipped = (SELECT COUNT(*) FROM run_inputs WHERE run_id=?1
                       AND decision NOT IN ('process', 'duplicate')),
            duplicate_count = (SELECT COUNT(*) FROM run_inputs WHERE run_id=?1 AND decision='duplicate'),
            processed = (SELECT COUNT(*) FROM extraction_results WHERE run_id=?1),
            succeeded = (SELECT COUNT(*) FROM extraction_results WHERE run_id=?1 AND status='ok'),
            failed = (SELECT COUNT(*) FROM extraction_results WHERE run_id=?1 AND status='error'),
            review_case_count = (SELECT COUNT(*) FROM review_cases WHERE run_id=?1 AND status='open')
         WHERE id=?1",
        params![run_id, status],
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

/// Reconcile abandoned runs: every extraction_run still marked `running` at
/// the start of a new invocation is cancelled, its pending/running results
/// are set to `cancelled`, and the run receives an operational error code.
/// Returns the number of abandoned runs recovered.
///
/// Each run is wrapped in try/except so one corrupt run does not prevent
/// recovery of the others (Python `_reconcile_abandoned_runs` semantics).
pub fn reconcile_abandoned_runs(conn: &Connection) -> Result<usize, DbError> {
    let mut stmt =
        conn.prepare("SELECT id FROM extraction_runs WHERE status='running' ORDER BY created_at")?;

    let run_ids: Vec<String> = stmt
        .query_map([], |r| r.get::<_, String>(0))
        .map_err(DbError::from)?
        .filter_map(|row| row.ok())
        .collect();

    let mut recovered = 0usize;

    for run_id in run_ids {
        if let Err(e) = reconcile_one_abandoned_run(conn, &run_id) {
            // One corrupt run does NOT prevent recovery of others.
            let _ = e;
            continue;
        }
        recovered += 1;
    }

    Ok(recovered)
}

fn reconcile_one_abandoned_run(conn: &Connection, run_id: &str) -> Result<(), DbError> {
    const ERROR: &str = "abandoned_run_recovered";

    // Cancel results left pending/running by the crashed process.
    conn.execute(
        "UPDATE extraction_results
         SET status='cancelled', error_type='cancelled', error_message=?2,
             updated_at=datetime('now')
         WHERE run_id=?1 AND status IN ('pending', 'running')",
        params![run_id, ERROR],
    )?;

    // Heal process inputs that never produced a result (Python creates a
    // cancelled result so `run_inputs_process_without_one_result` stays clean).
    conn.execute(
        "INSERT INTO extraction_results
            (id, run_id, run_input_id, image_file_id, status, error_type,
             error_message, model, prompt_snapshot_id, created_at, updated_at)
         SELECT 'res-recovered-' || ri.id, ri.run_id, ri.id, ri.image_file_id,
                'cancelled', 'cancelled', ?2, r.model, r.prompt_snapshot_id,
                datetime('now'), datetime('now')
         FROM run_inputs ri
         JOIN extraction_runs r ON r.id = ri.run_id
         LEFT JOIN extraction_results er ON er.run_input_id = ri.id
         WHERE ri.run_id = ?1 AND ri.decision = 'process' AND er.id IS NULL",
        params![run_id, ERROR],
    )?;

    // Recompute the stored counters from relational rows (Python run_metrics).
    conn.execute(
        "UPDATE extraction_runs SET
            total_inputs = (SELECT COUNT(*) FROM run_inputs WHERE run_id=?1),
            to_process = (SELECT COUNT(*) FROM run_inputs WHERE run_id=?1 AND decision='process'),
            skipped = (SELECT COUNT(*) FROM run_inputs WHERE run_id=?1
                       AND decision NOT IN ('process', 'duplicate')),
            duplicate_count = (SELECT COUNT(*) FROM run_inputs WHERE run_id=?1 AND decision='duplicate'),
            processed = (SELECT COUNT(*) FROM extraction_results WHERE run_id=?1),
            succeeded = (SELECT COUNT(*) FROM extraction_results WHERE run_id=?1 AND status='ok'),
            failed = (SELECT COUNT(*) FROM extraction_results WHERE run_id=?1 AND status='error'),
            review_case_count = (SELECT COUNT(*) FROM review_cases WHERE run_id=?1 AND status='open')
         WHERE id=?1",
        params![run_id],
    )?;

    // Finalize the run as failed with the recovered error identity.
    conn.execute(
        "UPDATE extraction_runs
         SET status='failed', operational_error_code=?2, operational_error_message=?2,
             finished_at=datetime('now')
         WHERE id=?1 AND status='running'",
        params![run_id, ERROR],
    )?;

    Ok(())
}
