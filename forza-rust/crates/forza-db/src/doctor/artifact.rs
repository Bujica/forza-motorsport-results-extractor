//! Model-artifact and evidence checks (artifact_checks.py).

use std::path::Path;

use rusqlite::Connection;

use crate::error::DbError;

use super::helpers::{check_sql, file_matches_size_and_sha256, scalar, scalar_params, sha256_hex};
use super::run::result_input_parent_mismatch_check;
use super::types::{DoctorCheck, DoctorSeverity};

// ── Python-compatible canonical JSON serialization ───────────────────────────
// `json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))`

fn python_json_string(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => {
                out.push_str(&format!("\\u{:04x}", c as u32));
            }
            c if (c as u32) <= 0x7e => out.push(c),
            c => {
                // ensure_ascii escapes everything above ~; astral chars become
                // UTF-16 surrogate pairs.
                let code = c as u32;
                if code <= 0xFFFF {
                    out.push_str(&format!("\\u{code:04x}"));
                } else {
                    let v = code - 0x1_0000;
                    let hi = 0xD800 + (v >> 10);
                    let lo = 0xDC00 + (v & 0x3FF);
                    out.push_str(&format!("\\u{hi:04x}\\u{lo:04x}"));
                }
            }
        }
    }
    out.push('"');
    out
}

fn opt_json_string(value: Option<&str>) -> String {
    match value {
        Some(s) => python_json_string(s),
        None => "null".to_string(),
    }
}

/// Matches `prompts.prompt_payload_hash`.
fn prompt_payload_hash(
    system_text: &str,
    user_text_template: Option<&str>,
    response_schema_json: Option<&str>,
) -> String {
    let canonical = format!(
        "{{\"response_schema_json\":{},\"system_text\":{},\"user_text_template\":{}}}",
        opt_json_string(response_schema_json),
        python_json_string(system_text),
        opt_json_string(user_text_template),
    );
    sha256_hex(canonical.as_bytes())
}

use crate::evidence::canonical_request_hash;

// ── Artifact checks (artifact_checks.py) ─────────────────────────────────────

fn attempt_has_debug_evidence(
    raw_response: &str,
    parse_error: &str,
    error_code: &str,
    error_message: &str,
    rejected_reason: &str,
    validation_issues: &str,
) -> bool {
    !raw_response.is_empty()
        || !parse_error.is_empty()
        || !error_code.is_empty()
        || !error_message.is_empty()
        || !rejected_reason.is_empty()
        || !validation_issues.is_empty()
}

/// Artifact rows with their stored hash/size and the SQL-evidence state of
/// their backing attempt, if any.
struct ArtifactRow {
    artifact_type: String,
    attempt_id: Option<String>,
    file_path: String,
    sha256: Option<String>,
    size_bytes: Option<i64>,
}

fn load_artifact_rows(
    conn: &Connection,
    canonical_only: bool,
) -> Result<Vec<ArtifactRow>, DbError> {
    let filter = if canonical_only {
        " WHERE is_canonical = 1"
    } else {
        ""
    };
    let sql = format!(
        "SELECT artifact_type, attempt_id, file_path, sha256, size_bytes
         FROM model_artifacts{filter}"
    );
    let mut stmt = conn.prepare(&sql)?;
    let rows = stmt.query_map([], |row| {
        Ok(ArtifactRow {
            artifact_type: row.get(0)?,
            attempt_id: row.get(1)?,
            file_path: row.get(2)?,
            sha256: row.get(3)?,
            size_bytes: row.get(4)?,
        })
    })?;
    rows.collect::<Result<Vec<_>, _>>().map_err(DbError::from)
}

/// Attempt evidence for `{attempt_id, artifact_type}` pairs, mirroring
/// `_artifact_sql_evidence_keys`: raw_response artifacts are covered by
/// non-empty `raw_response`, failed_attempt artifacts by debug evidence on
/// error attempts.
fn attempt_has_sql_evidence(
    conn: &Connection,
    attempt_id: &str,
    artifact_type: &str,
) -> Result<bool, DbError> {
    if artifact_type != "raw_response" && artifact_type != "failed_attempt" {
        return Ok(false);
    }
    let row = conn.query_row(
        "SELECT COALESCE(raw_response, ''), COALESCE(status, ''), COALESCE(parse_error, ''),
                COALESCE(error_code, ''), COALESCE(error_message, ''),
                COALESCE(rejected_reason, ''), COALESCE(validation_issues_json, '')
         FROM extraction_attempts WHERE id = ?1",
        [attempt_id],
        |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, String>(4)?,
                row.get::<_, String>(5)?,
                row.get::<_, String>(6)?,
            ))
        },
    );
    match row {
        Err(rusqlite::Error::QueryReturnedNoRows) => Ok(false),
        Err(e) => Err(e.into()),
        Ok((
            raw_response,
            status,
            parse_error,
            error_code,
            error_message,
            rejected,
            validation,
        )) => {
            if artifact_type == "raw_response" {
                Ok(!raw_response.is_empty())
            } else {
                Ok(status == "error"
                    && attempt_has_debug_evidence(
                        &raw_response,
                        &parse_error,
                        &error_code,
                        &error_message,
                        &rejected,
                        &validation,
                    ))
            }
        }
    }
}

fn invalid_file_artifacts(conn: &Connection, artifacts: Vec<ArtifactRow>) -> Result<i64, DbError> {
    let mut invalid = 0i64;
    for artifact in artifacts {
        if let Some(attempt_id) = artifact.attempt_id.as_deref()
            && attempt_has_sql_evidence(conn, attempt_id, &artifact.artifact_type)?
        {
            continue;
        }
        if !file_matches_size_and_sha256(
            Path::new(&artifact.file_path),
            artifact.size_bytes,
            artifact.sha256.as_deref(),
        ) {
            invalid += 1;
        }
    }
    Ok(invalid)
}

fn is_dry_run(mode: &str, config_extra_json: Option<&str>) -> bool {
    if mode == "dry_run" {
        return true;
    }
    config_extra_json
        .and_then(|text| serde_json::from_str::<serde_json::Value>(text).ok())
        .and_then(|config| config.get("dry_run").cloned())
        .is_some_and(|flag| match flag {
            serde_json::Value::Bool(b) => b,
            serde_json::Value::Number(n) => n.as_f64().is_some_and(|f| f != 0.0),
            serde_json::Value::String(s) => !s.is_empty(),
            serde_json::Value::Null => false,
            _ => true,
        })
}

pub(super) fn artifact_checks(conn: &Connection) -> Result<Vec<DoctorCheck>, DbError> {
    let ok_without_accepted = check_sql(
        conn,
        "ok_results_without_accepted_attempt",
        DoctorSeverity::Error,
        "Successful extraction results must point to an accepted attempt.",
        r#"
            SELECT COUNT(*) FROM extraction_results
            WHERE status = 'ok' AND accepted_attempt_id IS NULL
        "#,
    )?;

    let accepted_pointer = check_sql(
        conn,
        "accepted_attempt_pointer_invalid",
        DoctorSeverity::Error,
        "accepted_attempt_id must point to an accepted ok attempt.",
        r#"
            SELECT COUNT(*)
            FROM extraction_results er
            LEFT JOIN extraction_attempts a ON a.id = er.accepted_attempt_id
            WHERE er.accepted_attempt_id IS NOT NULL
              AND (a.id IS NULL OR a.accepted <> 1 OR a.status <> 'ok')
        "#,
    )?;

    let error_with_laps = check_sql(
        conn,
        "error_results_with_laps",
        DoctorSeverity::Error,
        "Error extraction results must not have lap_records.",
        r#"
            SELECT COUNT(*)
            FROM extraction_results er
            JOIN lap_records lr ON lr.extraction_result_id = er.id
            WHERE er.status = 'error'
        "#,
    )?;

    let accepted_missing_evidence = check_sql(
        conn,
        "accepted_attempts_missing_raw_evidence",
        DoctorSeverity::Error,
        "Accepted attempts must have raw_response text or a canonical raw_response artifact.",
        r#"
            SELECT COUNT(*)
            FROM extraction_attempts a
            WHERE a.accepted = 1
              AND COALESCE(a.raw_response, '') = ''
              AND NOT EXISTS (
                  SELECT 1 FROM model_artifacts ma
                  WHERE ma.attempt_id = a.id
                    AND ma.artifact_type = 'raw_response'
                    AND ma.is_canonical = 1
              )
        "#,
    )?;

    let canonical_invalid = invalid_file_artifacts(conn, load_artifact_rows(conn, true)?)?;
    let canonical_invalid_check = DoctorCheck::new(
        "canonical_artifacts_invalid",
        DoctorSeverity::Error,
        "File-backed canonical model artifacts must exist and match sha256/size_bytes; SQL-backed raw evidence is validated from extraction_attempts.",
        canonical_invalid,
    );

    let model_invalid = invalid_file_artifacts(conn, load_artifact_rows(conn, false)?)?;
    let model_invalid_check = DoctorCheck::new(
        "model_artifacts_invalid",
        DoctorSeverity::Error,
        "Every file-backed model artifact must exist and match sha256/size_bytes; SQL-backed raw evidence is validated from extraction_attempts.",
        model_invalid,
    );

    let runs_missing_snapshot = scalar(
        conn,
        r#"
            SELECT COUNT(*) FROM extraction_runs r
            WHERE r.prompt_snapshot_id IS NULL
               OR r.prompt_snapshot_id NOT IN (SELECT id FROM prompt_snapshots)
        "#,
    )?;
    let runs_missing_snapshot_check = DoctorCheck::new(
        "runs_missing_prompt_snapshot",
        DoctorSeverity::Error,
        "Run prompt_snapshot_id must point to immutable prompt content.",
        runs_missing_snapshot,
    );

    let prompt_integrity = invalid_prompt_snapshots(conn)?;
    let prompt_integrity_check = DoctorCheck::new(
        "prompt_snapshot_integrity_invalid",
        DoctorSeverity::Error,
        "Prompt snapshot id/hash must match its canonical immutable content.",
        prompt_integrity,
    );

    let prompt_mismatch = check_sql(
        conn,
        "run_prompt_snapshot_mismatch",
        DoctorSeverity::Error,
        "Run prompt_name/prompt_hash must match its linked prompt snapshot.",
        r#"
            SELECT COUNT(*)
            FROM extraction_runs r
            JOIN prompt_snapshots p ON p.id = r.prompt_snapshot_id
            WHERE r.prompt_name <> p.prompt_name
               OR r.prompt_hash <> p.content_hash
               OR r.prompt_name IS NULL
               OR r.prompt_hash IS NULL
        "#,
    )?;

    let result_parent = result_input_parent_mismatch_check(conn)?;

    let runtime_missing = runs_after_preflight_missing_snapshot(conn)?;
    let runtime_missing_check = DoctorCheck::new(
        "runs_after_preflight_missing_runtime_snapshot",
        DoctorSeverity::Error,
        "Runs that reached LM Studio preflight must have one preflight runtime snapshot.",
        runtime_missing,
    );

    let export_invalid = invalid_export_artifacts(conn)?;
    let export_invalid_check = DoctorCheck::new(
        "export_artifacts_invalid",
        DoctorSeverity::Error,
        "Export artifacts must exist and match registered hash/size.",
        export_invalid,
    );

    let image_payload = request_messages_with_image_payload(conn)?;
    let image_payload_check = DoctorCheck::new(
        "request_messages_contain_image_payload",
        DoctorSeverity::Error,
        "Stored request_messages_json must be redacted and contain no image base64 payload.",
        image_payload,
    );

    let request_hash = invalid_request_hashes(conn)?;
    let request_hash_check = DoctorCheck::new(
        "request_hash_invalid",
        DoctorSeverity::Error,
        "request_hash must recompute from persisted redacted request payload.",
        request_hash,
    );

    let attempts_missing_runtime = scalar(
        conn,
        "SELECT COUNT(*) FROM extraction_attempts WHERE runtime_snapshot_id IS NULL",
    )?;
    let attempts_missing_runtime_check = DoctorCheck::new(
        "attempts_missing_runtime_snapshot",
        DoctorSeverity::Error,
        "Every real chat attempt must identify the observed runtime snapshot.",
        attempts_missing_runtime,
    );

    let attempt_parent = check_sql(
        conn,
        "attempt_parent_mismatch",
        DoctorSeverity::Error,
        "Attempt run/source links must match their extraction_result.",
        r#"
            SELECT COUNT(*)
            FROM extraction_attempts a
            JOIN extraction_results er ON er.id = a.extraction_result_id
            WHERE a.run_id <> er.run_id
               OR a.image_file_id <> er.image_file_id
        "#,
    )?;

    let accepted_parent = check_sql(
        conn,
        "accepted_attempt_parent_mismatch",
        DoctorSeverity::Error,
        "accepted_attempt_id must belong to the same extraction_result.",
        r#"
            SELECT COUNT(*)
            FROM extraction_results er
            JOIN extraction_attempts a ON a.id = er.accepted_attempt_id
            WHERE a.extraction_result_id <> er.id
        "#,
    )?;

    let attempt_count = check_sql(
        conn,
        "result_attempt_count_mismatch",
        DoctorSeverity::Error,
        "extraction_results.attempt_count must match persisted attempts.",
        r#"
            SELECT COUNT(*)
            FROM extraction_results er
            WHERE er.attempt_count <> (
                SELECT COUNT(*) FROM extraction_attempts a
                WHERE a.extraction_result_id = er.id
            )
        "#,
    )?;

    let result_prompt = check_sql(
        conn,
        "result_prompt_mismatch",
        DoctorSeverity::Error,
        "Every result must retain the immutable prompt snapshot of its run.",
        r#"
            SELECT COUNT(*)
            FROM extraction_results er
            JOIN extraction_runs r ON r.id = er.run_id
            WHERE er.prompt_snapshot_id IS NULL
               OR er.prompt_snapshot_id <> r.prompt_snapshot_id
        "#,
    )?;

    let runtime_parent = check_sql(
        conn,
        "attempt_runtime_parent_mismatch",
        DoctorSeverity::Error,
        "Attempt runtime snapshots must belong to the same run.",
        r#"
            SELECT COUNT(*)
            FROM extraction_attempts a
            JOIN model_runtime_snapshots s ON s.id = a.runtime_snapshot_id
            WHERE a.run_id <> s.run_id
        "#,
    )?;

    let canonical_without_attempt = check_sql(
        conn,
        "canonical_artifacts_without_attempt",
        DoctorSeverity::Error,
        "Canonical raw response artifacts must belong to a real attempt.",
        r#"
            SELECT COUNT(*) FROM model_artifacts
            WHERE is_canonical = 1
              AND artifact_type = 'raw_response'
              AND attempt_id IS NULL
        "#,
    )?;

    let model_parent = check_sql(
        conn,
        "model_artifact_parent_mismatch",
        DoctorSeverity::Error,
        "Model artifact run/source/result/attempt links must describe one evidence chain.",
        r#"
            SELECT COUNT(*)
            FROM model_artifacts ma
            LEFT JOIN extraction_results er ON er.id = ma.extraction_result_id
            LEFT JOIN extraction_attempts a ON a.id = ma.attempt_id
            WHERE (
                ma.extraction_result_id IS NOT NULL
                AND (
                    er.id IS NULL
                    OR ma.run_id IS NOT er.run_id
                    OR ma.image_file_id IS NOT er.image_file_id
                )
            )
            OR (
                ma.attempt_id IS NOT NULL
                AND (
                    a.id IS NULL
                    OR ma.run_id IS NOT a.run_id
                    OR ma.image_file_id IS NOT a.image_file_id
                    OR ma.extraction_result_id IS NOT a.extraction_result_id
                )
            )
        "#,
    )?;

    let error_attempts = error_attempts_missing_sql_evidence(conn)?;
    let error_attempts_check = DoctorCheck::new(
        "error_attempts_missing_sql_evidence",
        DoctorSeverity::Error,
        "Failed attempts must retain SQL debug evidence such as raw_response, parse_error, or error_message.",
        error_attempts,
    );

    Ok(vec![
        ok_without_accepted,
        accepted_pointer,
        error_with_laps,
        accepted_missing_evidence,
        canonical_invalid_check,
        model_invalid_check,
        runs_missing_snapshot_check,
        prompt_integrity_check,
        prompt_mismatch,
        result_parent,
        runtime_missing_check,
        export_invalid_check,
        image_payload_check,
        request_hash_check,
        attempts_missing_runtime_check,
        attempt_parent,
        accepted_parent,
        attempt_count,
        result_prompt,
        runtime_parent,
        canonical_without_attempt,
        model_parent,
        error_attempts_check,
    ])
}

fn invalid_prompt_snapshots(conn: &Connection) -> Result<i64, DbError> {
    let mut stmt = conn.prepare(
        "SELECT id, prompt_name, content_hash, system_text, user_text_template, response_schema_json
         FROM prompt_snapshots",
    )?;
    let rows = stmt.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, String>(3)?,
            row.get::<_, Option<String>>(4)?,
            row.get::<_, Option<String>>(5)?,
        ))
    })?;

    let mut invalid = 0i64;
    for row in rows {
        let (id, prompt_name, content_hash, system_text, user_template, response_schema) = row?;
        let expected = prompt_payload_hash(
            &system_text,
            user_template.as_deref(),
            response_schema.as_deref(),
        );
        if content_hash != expected || id != format!("{prompt_name}:{expected}") {
            invalid += 1;
        }
    }
    Ok(invalid)
}

fn runs_after_preflight_missing_snapshot(conn: &Connection) -> Result<i64, DbError> {
    let mut stmt = conn.prepare(
        "SELECT id, status, mode, COALESCE(config_extra_json, ''),
                to_process, processed, succeeded, failed
         FROM extraction_runs WHERE status IN ('completed', 'cancelled')",
    )?;
    let rows = stmt.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, String>(3)?,
            row.get::<_, i64>(4)?,
            row.get::<_, i64>(5)?,
            row.get::<_, i64>(6)?,
            row.get::<_, i64>(7)?,
        ))
    })?;

    let mut missing = 0i64;
    for row in rows {
        let (id, status, mode, config_json, to_process, processed, succeeded, failed) = row?;
        if is_dry_run(&mode, Some(&config_json)) {
            continue;
        }
        let has_results = scalar_params(
            conn,
            "SELECT COUNT(*) FROM extraction_results WHERE run_id = ?1",
            &[&id],
        )? > 0;
        let requires_preflight = (status == "completed" && to_process > 0)
            || processed > 0
            || succeeded > 0
            || failed > 0
            || has_results;
        if !requires_preflight {
            continue;
        }
        let has_snapshot = scalar_params(
            conn,
            "SELECT COUNT(*) FROM model_runtime_snapshots
             WHERE run_id = ?1 AND snapshot_kind = 'preflight'",
            &[&id],
        )? > 0;
        if !has_snapshot {
            missing += 1;
        }
    }
    Ok(missing)
}

fn invalid_export_artifacts(conn: &Connection) -> Result<i64, DbError> {
    let mut stmt = conn.prepare("SELECT file_path, sha256, size_bytes FROM export_artifacts")?;
    let rows = stmt.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, Option<String>>(1)?,
            row.get::<_, Option<i64>>(2)?,
        ))
    })?;

    let mut invalid = 0i64;
    for row in rows {
        let (file_path, sha256, size_bytes) = row?;
        if !file_matches_size_and_sha256(Path::new(&file_path), size_bytes, sha256.as_deref()) {
            invalid += 1;
        }
    }
    Ok(invalid)
}

fn request_messages_with_image_payload(conn: &Connection) -> Result<i64, DbError> {
    let mut stmt = conn.prepare(
        "SELECT request_messages_json FROM extraction_attempts
         WHERE request_messages_json IS NOT NULL",
    )?;
    let rows = stmt.query_map([], |row| row.get::<_, String>(0))?;

    let mut bad = 0i64;
    for row in rows {
        let payload = row?;
        let lowered = payload.to_lowercase();
        if lowered.contains("data:image") || lowered.contains("base64") {
            bad += 1;
        }
    }
    Ok(bad)
}

fn invalid_request_hashes(conn: &Connection) -> Result<i64, DbError> {
    let mut stmt = conn.prepare(
        "SELECT a.request_messages_json, a.request_config_json, a.model,
                a.request_image_format, a.request_image_mime_type,
                a.request_image_width, a.request_image_height, a.request_image_bytes,
                a.request_hash, er.prompt_snapshot_id, im.file_hash
         FROM extraction_attempts a
         JOIN extraction_results er ON er.id = a.extraction_result_id
         JOIN image_files im ON im.id = a.image_file_id",
    )?;
    let rows = stmt.query_map([], |row| {
        Ok((
            row.get::<_, Option<String>>(0)?,
            row.get::<_, Option<String>>(1)?,
            row.get::<_, Option<String>>(2)?,
            row.get::<_, Option<String>>(3)?,
            row.get::<_, Option<String>>(4)?,
            row.get::<_, Option<i64>>(5)?,
            row.get::<_, Option<i64>>(6)?,
            row.get::<_, Option<i64>>(7)?,
            row.get::<_, Option<String>>(8)?,
            row.get::<_, Option<String>>(9)?,
            row.get::<_, Option<String>>(10)?,
        ))
    })?;

    let mut invalid = 0i64;
    for row in rows {
        let (
            request_messages,
            request_config,
            model,
            image_format,
            image_mime,
            image_width,
            image_height,
            image_bytes,
            request_hash,
            prompt_snapshot_id,
            source_file_hash,
        ) = row?;
        let Some(stored_hash) = request_hash.filter(|h| !h.is_empty()) else {
            invalid += 1;
            continue;
        };
        let expected = canonical_request_hash(
            request_messages.as_deref(),
            request_config.as_deref(),
            prompt_snapshot_id.as_deref(),
            model.as_deref(),
            source_file_hash.as_deref(),
            image_format.as_deref(),
            image_mime.as_deref(),
            image_width,
            image_height,
            image_bytes,
        );
        if expected != stored_hash {
            invalid += 1;
        }
    }
    Ok(invalid)
}

fn error_attempts_missing_sql_evidence(conn: &Connection) -> Result<i64, DbError> {
    let mut stmt = conn.prepare(
        "SELECT COALESCE(raw_response, ''), COALESCE(parse_error, ''), COALESCE(error_code, ''),
                COALESCE(error_message, ''), COALESCE(rejected_reason, ''),
                COALESCE(validation_issues_json, '')
         FROM extraction_attempts WHERE status = 'error'",
    )?;
    let rows = stmt.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, String>(3)?,
            row.get::<_, String>(4)?,
            row.get::<_, String>(5)?,
        ))
    })?;

    let mut missing = 0i64;
    for row in rows {
        let (raw, parse_error, error_code, error_message, rejected, validation) = row?;
        if !attempt_has_debug_evidence(
            &raw,
            &parse_error,
            &error_code,
            &error_message,
            &rejected,
            &validation,
        ) {
            missing += 1;
        }
    }
    Ok(missing)
}
