//! Full DB doctor battery ported from `forza/application/db_doctor/`.
//!
//! Checks are grouped like the Python modules: SQLite integrity, status
//! vocabulary, run/input contract, image files, best-lap state, reviews,
//! artifacts, and schema drift. Filesystem-backed checks (image bytes,
//! artifact hashes) read the files referenced by database rows.

use std::collections::{BTreeMap, HashSet};
use std::path::Path;

use rusqlite::Connection;
use sha2::{Digest, Sha256};

use crate::error::DbError;
use crate::migration::{SCHEMA_VERSION, SchemaStatus, schema_status, user_version};
use crate::schema_ddl::{INDEX_DDL, TABLE_DDL};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DoctorSeverity {
    Error,
    Warning,
    Info,
}

impl DoctorSeverity {
    pub fn as_str(self) -> &'static str {
        match self {
            DoctorSeverity::Error => "error",
            DoctorSeverity::Warning => "warning",
            DoctorSeverity::Info => "info",
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct DoctorCheck {
    pub key: &'static str,
    pub ok: bool,
    pub count: i64,
    pub detail: String,
    pub severity: DoctorSeverity,
}

impl DoctorCheck {
    fn new(
        key: &'static str,
        severity: DoctorSeverity,
        detail: impl Into<String>,
        count: i64,
    ) -> Self {
        DoctorCheck {
            key,
            ok: count == 0,
            count,
            detail: detail.into(),
            severity,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct DoctorReport {
    pub ok: bool,
    pub schema_status: String,
    pub user_version: i64,
    pub checks: Vec<DoctorCheck>,
}

impl DoctorReport {
    fn finish(mut self) -> Self {
        self.ok = self.schema_status == "current"
            && self
                .checks
                .iter()
                .all(|c| c.severity != DoctorSeverity::Error || c.ok);
        self
    }
}

// ── helpers ──────────────────────────────────────────────────────────────────

fn scalar(conn: &Connection, sql: &str) -> Result<i64, DbError> {
    conn.query_row(sql, [], |row| row.get(0))
        .map_err(DbError::from)
}

fn scalar_params(
    conn: &Connection,
    sql: &str,
    params: &[&dyn rusqlite::ToSql],
) -> Result<i64, DbError> {
    conn.query_row(sql, params, |row| row.get(0))
        .map_err(DbError::from)
}

fn check_sql(
    conn: &Connection,
    key: &'static str,
    severity: DoctorSeverity,
    detail: &str,
    sql: &str,
) -> Result<DoctorCheck, DbError> {
    let count = scalar(conn, sql)?;
    Ok(DoctorCheck::new(key, severity, detail, count))
}

/// Count the groups produced by a `GROUP BY ... HAVING` query.
fn check_sql_groups(
    conn: &Connection,
    key: &'static str,
    severity: DoctorSeverity,
    detail: &str,
    group_sql: &str,
) -> Result<DoctorCheck, DbError> {
    let count = scalar(conn, &format!("SELECT COUNT(*) FROM ({group_sql})"))?;
    Ok(DoctorCheck::new(key, severity, detail, count))
}

fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    format!("{digest:x}")
}

fn sha256_file(path: &Path) -> std::io::Result<String> {
    let mut file = std::fs::File::open(path)?;
    let mut hasher = Sha256::new();
    std::io::copy(&mut file, &mut hasher)?;
    Ok(format!("{:x}", hasher.finalize()))
}

/// `{sha256_hex}_{size}` — matches `pipeline.image.file_hash`.
fn image_file_hash(path: &Path) -> std::io::Result<String> {
    let hex = sha256_file(path)?;
    let size = std::fs::metadata(path)?.len();
    Ok(format!("{hex}_{size}"))
}

fn size_from_file_hash(value: &str) -> Option<i64> {
    let (_, size_text) = value.rsplit_once('_')?;
    size_text.parse().ok()
}

fn file_matches_size_and_sha256(
    path: &Path,
    expected_size: Option<i64>,
    expected_sha256: Option<&str>,
) -> bool {
    let (Some(expected_size), Some(expected_sha256)) = (expected_size, expected_sha256) else {
        return false;
    };
    let Ok(metadata) = std::fs::metadata(path) else {
        return false;
    };
    if !metadata.is_file() || metadata.len() != expected_size.unsigned_abs() {
        return false;
    }
    sha256_file(path).is_ok_and(|hex| hex == expected_sha256)
}

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

// ── SQLite integrity (sqlite_checks.py) ──────────────────────────────────────

fn integrity_check(conn: &Connection) -> Result<DoctorCheck, DbError> {
    let result: String = conn.query_row("PRAGMA integrity_check", [], |r| r.get(0))?;
    Ok(DoctorCheck::new(
        "sqlite_integrity_check",
        DoctorSeverity::Error,
        format!("integrity_check -> {result}"),
        i64::from(result != "ok"),
    ))
}

fn foreign_key_check(conn: &Connection) -> Result<DoctorCheck, DbError> {
    let mut stmt = conn.prepare("PRAGMA foreign_key_check")?;
    let violations = stmt.query_map([], |row| {
        Ok(format!(
            "{} row {} references {}",
            row.get::<_, String>(0)?,
            row.get::<_, i64>(1)?,
            row.get::<_, String>(2)?
        ))
    })?;
    let found: Vec<String> = violations.collect::<Result<_, _>>()?;
    let count = found.len() as i64;
    let detail = if found.is_empty() {
        "no foreign key violations".to_string()
    } else {
        format!("{} violation(s): {}", found.len(), found.join("; "))
    };
    Ok(DoctorCheck::new(
        "foreign_key_violations",
        DoctorSeverity::Error,
        detail,
        count,
    ))
}

// ── Status vocabulary (status_checks.py) ─────────────────────────────────────

const INVALID_STATUS_VALUES_SQL: &str = r#"
    SELECT
        (SELECT COUNT(*) FROM extraction_runs
         WHERE status NOT IN ('pending', 'running', 'completed', 'failed', 'cancelled'))
      + (SELECT COUNT(*) FROM extraction_results
         WHERE status NOT IN ('pending', 'running', 'ok', 'error', 'cancelled'))
      + (SELECT COUNT(*) FROM extraction_attempts
         WHERE status NOT IN ('ok', 'error', 'cancelled'))
      + (SELECT COUNT(*) FROM image_files
         WHERE file_status NOT IN ('available', 'missing')
            OR best_lap_status NOT IN ('pending', 'contributing', 'non_contributing'))
      + (SELECT COUNT(*) FROM review_cases
         WHERE status NOT IN ('open', 'resolved', 'ignored', 'auto_resolved')
            OR reason NOT IN ('dirty_lap', 'track', 'weather', 'race_class', 'car', 'driver_name')
            OR outcome NOT IN ('pending', 'confirmed', 'model_error', 'ignored')
            OR ("trigger" IS NOT NULL AND "trigger" NOT IN ('model_marked_dirty', 'weather_unknown', 'rain_time_suspicious', 'track_unknown', 'track_unresolved', 'track_not_in_reference', 'class_unknown', 'class_invalid', 'car_empty', 'car_not_in_reference', 'driver_name_empty', 'numeric_prefix', 'invalid_symbol'))
            OR (decision_field IS NOT NULL AND decision_field NOT IN ('dirty', 'track', 'weather', 'race_class', 'car', 'driver')))
      + (SELECT COUNT(*) FROM image_flags
         WHERE status NOT IN ('active', 'resolved', 'ignored')
            OR flag_scope NOT IN ('image', 'lap')
            OR flag_type NOT IN ('duplicate', 'dirty_lap', 'track', 'weather', 'race_class', 'car', 'driver_name'))
"#;

pub fn invalid_status_values_check(conn: &Connection) -> Result<DoctorCheck, DbError> {
    check_sql(
        conn,
        "invalid_status_values",
        DoctorSeverity::Error,
        "Persisted lifecycle/status fields must use the DB vNext vocabulary.",
        INVALID_STATUS_VALUES_SQL,
    )
}

// ── Run checks (run_checks.py) ───────────────────────────────────────────────

pub fn run_counter_checks(conn: &Connection) -> Result<Vec<DoctorCheck>, DbError> {
    let left_running: i64 = conn.query_row(
        "SELECT COUNT(*) FROM extraction_runs WHERE status='running'",
        [],
        |r| r.get(0),
    )?;

    let running_check = DoctorCheck::new(
        "runs_left_running",
        DoctorSeverity::Error,
        format!("running runs: {left_running}"),
        left_running,
    );

    let mut stmt = conn.prepare(
        "SELECT r.id, r.total_inputs, r.to_process, r.skipped, r.duplicate_count,
                r.processed, r.succeeded, r.failed, r.review_case_count,
                (SELECT COUNT(*) FROM run_inputs ri WHERE ri.run_id = r.id) as actual_inputs,
                (SELECT COUNT(*) FROM run_inputs ri WHERE ri.run_id = r.id AND ri.decision='process') as actual_to_process,
                (SELECT COUNT(*) FROM run_inputs ri WHERE ri.run_id = r.id AND ri.decision NOT IN ('process','duplicate')) as actual_skipped,
                (SELECT COUNT(*) FROM run_inputs ri WHERE ri.run_id = r.id AND ri.decision='duplicate') as actual_duplicates,
                (SELECT COUNT(*) FROM extraction_results er WHERE er.run_id = r.id) as actual_processed,
                (SELECT COUNT(*) FROM extraction_results er WHERE er.run_id = r.id AND er.status='ok') as actual_succeeded,
                (SELECT COUNT(*) FROM extraction_results er WHERE er.run_id = r.id AND er.status='error') as actual_failed,
                (SELECT COUNT(*) FROM review_cases rc WHERE rc.run_id = r.id AND rc.status='open') as actual_review_cases
         FROM extraction_runs r",
    )?;

    let rows = stmt.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, i64>(1)?,
            row.get::<_, i64>(2)?,
            row.get::<_, i64>(3)?,
            row.get::<_, i64>(4)?,
            row.get::<_, i64>(5)?,
            row.get::<_, i64>(6)?,
            row.get::<_, i64>(7)?,
            row.get::<_, i64>(8)?,
            row.get::<_, i64>(9)?,
            row.get::<_, i64>(10)?,
            row.get::<_, i64>(11)?,
            row.get::<_, i64>(12)?,
            row.get::<_, i64>(13)?,
            row.get::<_, i64>(14)?,
            row.get::<_, i64>(15)?,
            row.get::<_, i64>(16)?,
        ))
    })?;

    let mut mismatched_runs = 0i64;
    let mut mismatches = Vec::new();
    for row in rows {
        let (
            id,
            total_inputs,
            to_process,
            skipped,
            duplicate_count,
            processed,
            succeeded,
            failed,
            review_case_count,
            actual_inputs,
            actual_to_process,
            actual_skipped,
            actual_duplicates,
            actual_processed,
            actual_succeeded,
            actual_failed,
            actual_review_cases,
        ) = row?;

        let mut run_mismatches: Vec<String> = Vec::new();
        if total_inputs != actual_inputs {
            run_mismatches.push(format!(
                "total_inputs: stored={total_inputs} actual={actual_inputs}"
            ));
        }
        if to_process != actual_to_process {
            run_mismatches.push(format!(
                "to_process: stored={to_process} actual={actual_to_process}"
            ));
        }
        if skipped != actual_skipped {
            run_mismatches.push(format!("skipped: stored={skipped} actual={actual_skipped}"));
        }
        if duplicate_count != actual_duplicates {
            run_mismatches.push(format!(
                "duplicate_count: stored={duplicate_count} actual={actual_duplicates}"
            ));
        }
        if processed != actual_processed {
            run_mismatches.push(format!(
                "processed: stored={processed} actual={actual_processed}"
            ));
        }
        if succeeded != actual_succeeded {
            run_mismatches.push(format!(
                "succeeded: stored={succeeded} actual={actual_succeeded}"
            ));
        }
        if failed != actual_failed {
            run_mismatches.push(format!("failed: stored={failed} actual={actual_failed}"));
        }
        if review_case_count != actual_review_cases {
            run_mismatches.push(format!(
                "review_case_count: stored={review_case_count} actual={actual_review_cases}"
            ));
        }
        if !run_mismatches.is_empty() {
            mismatched_runs += 1;
            mismatches.push(format!("run {id}: {}", run_mismatches.join("; ")));
        }
    }

    let counter_detail = if mismatches.is_empty() {
        "all counters match".to_string()
    } else {
        format!(
            "{} mismatched run(s): {}",
            mismatched_runs,
            mismatches.join("; ")
        )
    };
    let counter_check = DoctorCheck::new(
        "run_counters_mismatch",
        DoctorSeverity::Error,
        counter_detail,
        mismatched_runs,
    );

    Ok(vec![running_check, counter_check])
}

fn run_input_contract_checks(conn: &Connection) -> Result<Vec<DoctorCheck>, DbError> {
    let contract = check_sql(
        conn,
        "run_input_contract_invalid",
        DoctorSeverity::Error,
        "run_inputs decisions and reason fields must not be overloaded.",
        r#"
            SELECT COUNT(*)
            FROM run_inputs
            WHERE decision NOT IN (
                'process', 'skip', 'duplicate', 'missing',
                'unsupported', 'outside_input', 'hash_failed'
            )
               OR (decision <> 'process' AND process_reason IS NOT NULL)
               OR (decision = 'process' AND (skip_reason IS NOT NULL OR duplicate_kind IS NOT NULL))
               OR (decision = 'duplicate' AND duplicate_kind IS NULL)
               OR (decision <> 'duplicate' AND duplicate_kind IS NOT NULL)
               OR (duplicate_kind IS NOT NULL AND duplicate_kind NOT IN ('hash', 'batch'))
        "#,
    )?;

    let duplicate_link = check_sql(
        conn,
        "run_input_duplicate_link_invalid",
        DoctorSeverity::Error,
        "Duplicate inputs must retain valid same-run canonical hash/link evidence.",
        r#"
            SELECT COUNT(*)
            FROM run_inputs d
            LEFT JOIN run_inputs p ON p.id = d.duplicate_of_input_id
            WHERE (
                d.decision = 'duplicate'
                AND (
                    d.file_hash IS NULL
                    OR d.duplicate_of_hash IS NULL
                    OR d.file_hash <> d.duplicate_of_hash
                    OR (d.duplicate_kind = 'batch' AND d.duplicate_of_input_id IS NULL)
                    OR (
                        d.duplicate_of_input_id IS NOT NULL
                        AND (
                            p.id IS NULL
                            OR p.run_id <> d.run_id
                            OR p.input_order >= d.input_order
                            OR p.file_hash <> d.duplicate_of_hash
                        )
                    )
                )
            )
            OR (
                d.decision <> 'duplicate'
                AND (
                    d.duplicate_of_hash IS NOT NULL
                    OR d.duplicate_of_input_id IS NOT NULL
                )
            )
        "#,
    )?;

    let final_runs = check_sql(
        conn,
        "final_runs_with_nonfinal_results",
        DoctorSeverity::Error,
        "Completed, failed, or cancelled runs cannot retain pending/running results.",
        r#"
            SELECT COUNT(*)
            FROM extraction_results er
            JOIN extraction_runs r ON r.id = er.run_id
            WHERE r.status IN ('completed', 'failed', 'cancelled')
              AND er.status IN ('pending', 'running')
        "#,
    )?;

    Ok(vec![contract, duplicate_link, final_runs])
}

fn run_input_process_checks(conn: &Connection) -> Result<Vec<DoctorCheck>, DbError> {
    let preflight = check_sql(
        conn,
        "preflight_failure_created_results",
        DoctorSeverity::Error,
        "Run-level operational/preflight failures must not create extraction results.",
        r#"
            SELECT COUNT(*)
            FROM extraction_runs r
            WHERE r.operational_error_code = 'lmstudio_preflight_failed'
              AND EXISTS (
                  SELECT 1 FROM extraction_results er WHERE er.run_id = r.id
              )
        "#,
    )?;

    let without_image = check_sql(
        conn,
        "run_inputs_process_without_image_file",
        DoctorSeverity::Error,
        "run_inputs with decision=process must have image_file_id.",
        "SELECT COUNT(*) FROM run_inputs WHERE decision = 'process' AND image_file_id IS NULL",
    )?;

    let without_result = check_sql_groups(
        conn,
        "run_inputs_process_without_one_result",
        DoctorSeverity::Error,
        "run_inputs with decision=process must have exactly one extraction_result.",
        r#"
            SELECT ri.id
            FROM run_inputs ri
            LEFT JOIN extraction_results er ON er.run_input_id = ri.id
            WHERE ri.decision = 'process'
            GROUP BY ri.id
            HAVING COUNT(er.id) <> 1
        "#,
    )?;

    Ok(vec![preflight, without_image, without_result])
}

fn result_input_parent_mismatch_check(conn: &Connection) -> Result<DoctorCheck, DbError> {
    check_sql(
        conn,
        "result_input_parent_mismatch",
        DoctorSeverity::Error,
        "Extraction result run/source links must match its run_input.",
        r#"
            SELECT COUNT(*)
            FROM extraction_results er
            JOIN run_inputs ri ON ri.id = er.run_input_id
            WHERE er.run_id IS NOT ri.run_id
               OR er.image_file_id IS NOT ri.image_file_id
        "#,
    )
}

// ── Image file checks (image_file_checks.py) ─────────────────────────────────

fn available_image_file_checks(conn: &Connection) -> Result<(i64, i64), DbError> {
    let mut stmt = conn.prepare(
        "SELECT current_path, file_hash FROM image_files WHERE file_status = 'available'",
    )?;
    let rows = stmt.query_map([], |row| {
        Ok((row.get::<_, Option<String>>(0)?, row.get::<_, String>(1)?))
    })?;

    let mut missing = 0i64;
    let mut mismatched = 0i64;
    for row in rows {
        let (current_path, expected_hash) = row?;
        let Some(path_str) = current_path else {
            missing += 1;
            continue;
        };
        let path = Path::new(&path_str);
        let metadata = match std::fs::metadata(path) {
            Ok(m) if m.is_file() => m,
            _ => {
                missing += 1;
                continue;
            }
        };
        if let Some(expected_size) = size_from_file_hash(&expected_hash)
            && metadata.len() != expected_size.unsigned_abs()
        {
            mismatched += 1;
            continue;
        }
        match image_file_hash(path) {
            Err(_) => missing += 1,
            Ok(actual) if actual != expected_hash => mismatched += 1,
            Ok(_) => {}
        }
    }
    Ok((missing, mismatched))
}

fn image_file_checks(conn: &Connection) -> Result<Vec<DoctorCheck>, DbError> {
    let (missing_files, mismatched_hashes) = available_image_file_checks(conn)?;

    let missing_metadata = check_sql(
        conn,
        "images_missing_metadata",
        DoctorSeverity::Warning,
        "Image files without physical metadata.",
        r#"
            SELECT COUNT(*) FROM image_files
            WHERE size_bytes IS NULL OR width_px IS NULL OR height_px IS NULL
        "#,
    )?;

    let path_conflicts = check_sql_groups(
        conn,
        "available_image_path_conflicts",
        DoctorSeverity::Error,
        "An available current_path may identify only one image file.",
        r#"
            SELECT current_path
            FROM image_files
            WHERE file_status = 'available' AND current_path IS NOT NULL
            GROUP BY current_path
            HAVING COUNT(*) > 1
        "#,
    )?;

    let missing_files_check = DoctorCheck::new(
        "available_images_missing_files",
        DoctorSeverity::Error,
        "Available image files must resolve to an existing current_path file.",
        missing_files,
    );
    let hash_mismatch_check = DoctorCheck::new(
        "available_images_hash_mismatch",
        DoctorSeverity::Error,
        "Available image file bytes must match their persisted file_hash.",
        mismatched_hashes,
    );

    Ok(vec![
        missing_metadata,
        path_conflicts,
        missing_files_check,
        hash_mismatch_check,
    ])
}

fn best_lap_value_checks(conn: &Connection) -> Result<Vec<DoctorCheck>, DbError> {
    let non_positive = check_sql(
        conn,
        "best_laps_without_positive_ms",
        DoctorSeverity::Error,
        "Rows marked as best laps must have positive best_lap_ms values.",
        r#"
            SELECT
                (SELECT COUNT(*) FROM lap_records
                 WHERE is_best_lap = 1 AND COALESCE(best_lap_ms, 0) <= 0)
              + (SELECT COUNT(*) FROM external_lap_records
                 WHERE active = 1 AND COALESCE(best_lap_ms, 0) <= 0)
        "#,
    )?;

    let dirty_marker = check_sql(
        conn,
        "clean_lap_contains_dirty_marker",
        DoctorSeverity::Error,
        "Clean canonical lap times must not retain dirty-lap markers.",
        r#"
            SELECT COUNT(*)
            FROM lap_records
            WHERE dirty = 0
              AND (
                  best_lap LIKE '%▲%'
                  OR best_lap LIKE '%⚠%'
                  OR best_lap LIKE '%†%'
              )
        "#,
    )?;

    Ok(vec![non_positive, dirty_marker])
}

fn lap_parent_checks(conn: &Connection) -> Result<Vec<DoctorCheck>, DbError> {
    let orphan = scalar(
        conn,
        r#"
            SELECT COUNT(*) FROM lap_records
            WHERE image_file_id NOT IN (SELECT id FROM image_files)
        "#,
    )?;
    let orphan_check = DoctorCheck::new(
        "laps_without_image_file",
        DoctorSeverity::Error,
        "Lap rows whose image file no longer exists.",
        orphan,
    );

    let parent = check_sql(
        conn,
        "lap_parent_mismatch",
        DoctorSeverity::Error,
        "Lap run/source links must match their extraction_result.",
        r#"
            SELECT COUNT(*)
            FROM lap_records l
            JOIN extraction_results er ON er.id = l.extraction_result_id
            WHERE l.run_id IS NOT er.run_id
               OR l.image_file_id IS NOT er.image_file_id
        "#,
    )?;

    Ok(vec![orphan_check, parent])
}

fn best_lap_status_checks(conn: &Connection) -> Result<Vec<DoctorCheck>, DbError> {
    let mut ids_with_best = HashSet::new();
    {
        let mut stmt =
            conn.prepare("SELECT image_file_id FROM lap_records WHERE is_best_lap = 1")?;
        let rows = stmt.query_map([], |row| row.get::<_, String>(0))?;
        for id in rows {
            ids_with_best.insert(id?);
        }
    }

    let mut stmt = conn.prepare("SELECT id, best_lap_status FROM image_files")?;
    let rows = stmt.query_map([], |row| {
        Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
    })?;

    let mut divergent = 0i64;
    for row in rows {
        let (image_id, status) = row?;
        let has_best = ids_with_best.contains(&image_id);
        if has_best != (status == "contributing") {
            divergent += 1;
        }
    }
    let divergent_check = DoctorCheck::new(
        "best_lap_status_divergent",
        DoctorSeverity::Warning,
        "Images marked as contributing without a best lap, or the reverse.",
        divergent,
    );

    let stale_pending = check_sql(
        conn,
        "best_lap_status_stale_pending",
        DoctorSeverity::Error,
        "Images with clean lap rows must not remain in pending best-lap status.",
        r#"
            SELECT COUNT(DISTINCT si.id)
            FROM image_files si
            JOIN lap_records lr ON lr.image_file_id = si.id
            WHERE si.best_lap_status = 'pending'
              AND si.file_status = 'available'
              AND lr.dirty = 0
              AND COALESCE(lr.best_lap_ms, 0) > 0
        "#,
    )?;

    Ok(vec![divergent_check, stale_pending])
}

// ── Review checks (review_checks.py) ─────────────────────────────────────────

fn review_core_checks(conn: &Connection) -> Result<Vec<DoctorCheck>, DbError> {
    let missing_flag = check_sql(
        conn,
        "open_reviews_missing_active_flag",
        DoctorSeverity::Error,
        "Every open review case must have a matching active image flag.",
        r#"
            SELECT COUNT(*)
            FROM review_cases rc
            WHERE rc.status = 'open'
              AND rc.image_file_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM image_flags f
                  WHERE f.image_file_id = rc.image_file_id
                    AND f.flag_type = rc.reason
                    AND COALESCE(f.lap_index, -1) = COALESCE(rc.lap_index, -1)
                    AND f.status = 'active'
              )
        "#,
    )?;

    let stale_flags = check_sql(
        conn,
        "stale_active_review_flags",
        DoctorSeverity::Error,
        "System review flags must resolve when their review case disappears.",
        r#"
            SELECT COUNT(*)
            FROM image_flags f
            WHERE f.status = 'active'
              AND f.created_by = 'system'
              AND f.flag_type IN (
                  'dirty_lap', 'track', 'weather',
                  'race_class', 'car', 'driver_name'
              )
              AND NOT EXISTS (
                  SELECT 1 FROM review_cases rc
                  WHERE rc.image_file_id = f.image_file_id
                    AND rc.reason = f.flag_type
                    AND COALESCE(rc.lap_index, -1) = COALESCE(f.lap_index, -1)
                    AND rc.status = 'open'
              )
        "#,
    )?;

    let invalid_reason = check_sql(
        conn,
        "review_cases_invalid_reason",
        DoctorSeverity::Error,
        "Review cases must use canonical reasons.",
        r#"
            SELECT COUNT(*) FROM review_cases
            WHERE reason NOT IN (
                'dirty_lap', 'track', 'weather',
                'race_class', 'car', 'driver_name'
            )
        "#,
    )?;

    let corrections_invalid = check_sql(
        conn,
        "review_corrections_invalid",
        DoctorSeverity::Error,
        "Review corrections must use stable source/lap/field identity and valid field names.",
        r#"
            SELECT COUNT(*)
            FROM review_corrections
            WHERE image_file_id IS NULL
               OR stable_key IS NULL
               OR stable_key = ''
               OR corrected_value IS NULL
               OR field NOT IN ('dirty', 'track', 'weather', 'race_class', 'car', 'driver')
               OR (field IN ('dirty', 'car', 'driver') AND lap_index IS NULL)
               OR (field IN ('track', 'weather', 'race_class') AND lap_index IS NOT NULL)
        "#,
    )?;

    Ok(vec![
        missing_flag,
        stale_flags,
        invalid_reason,
        corrections_invalid,
    ])
}

fn keys_containing_volatile_lap_ids(
    conn: &Connection,
    key_column: &str,
    table: &str,
) -> Result<i64, DbError> {
    let sql = format!(
        "SELECT {key_column}, lap_record_id FROM {table}
         WHERE lap_record_id IS NOT NULL"
    );
    let mut stmt = conn.prepare(&sql)?;
    let rows = stmt.query_map([], |row| {
        Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
    })?;
    let mut count = 0i64;
    for row in rows {
        let (key, lap_record_id) = row?;
        if key.contains(&lap_record_id) {
            count += 1;
        }
    }
    Ok(count)
}

fn review_model_error_identity_checks(conn: &Connection) -> Result<Vec<DoctorCheck>, DbError> {
    let missing_decision = check_sql(
        conn,
        "model_error_missing_decision",
        DoctorSeverity::Error,
        "Model-error reviews must store the corrected field and values.",
        r#"
            SELECT COUNT(*)
            FROM review_cases
            WHERE outcome = 'model_error'
              AND (
                  decision_field IS NULL
                  OR corrected_value IS NULL
                  OR model_value IS NULL
              )
        "#,
    )?;

    let missing_evidence = check_sql(
        conn,
        "model_error_missing_raw_evidence",
        DoctorSeverity::Error,
        "Model-error reviews must remain linked to raw model evidence.",
        r#"
            SELECT COUNT(*)
            FROM review_cases rc
            LEFT JOIN extraction_results er ON er.id = rc.extraction_result_id
            LEFT JOIN extraction_attempts a ON a.id = er.accepted_attempt_id
            WHERE rc.outcome = 'model_error'
              AND (
                  er.id IS NULL
                  OR (
                      COALESCE(a.raw_response, '') = ''
                      AND NOT EXISTS (
                          SELECT 1 FROM model_artifacts ma
                          WHERE ma.extraction_result_id = er.id
                            AND ma.artifact_type = 'raw_response'
                            AND ma.is_canonical = 1
                      )
                  )
              )
        "#,
    )?;

    let review_key_count = keys_containing_volatile_lap_ids(conn, "business_key", "review_cases")?;
    let review_key_check = DoctorCheck::new(
        "review_business_key_uses_lap_record_id",
        DoctorSeverity::Error,
        "review_cases.business_key must not depend on lap_record_id.",
        review_key_count,
    );

    let noncanonical = noncanonical_review_business_keys(conn)?;
    let noncanonical_check = DoctorCheck::new(
        "review_business_key_not_canonical",
        DoctorSeverity::Error,
        "review_cases.business_key must match the current canonical review identity.",
        noncanonical,
    );

    let orphan_source = scalar(
        conn,
        r#"
            SELECT COUNT(*) FROM review_corrections
            WHERE image_file_id NOT IN (SELECT id FROM image_files)
        "#,
    )?;
    let orphan_source_check = DoctorCheck::new(
        "review_corrections_orphan_source",
        DoctorSeverity::Error,
        "review_corrections.image_file_id must reference image_files.",
        orphan_source,
    );

    let flag_key_count = keys_containing_volatile_lap_ids(conn, "flag_key", "image_flags")?;
    let flag_key_check = DoctorCheck::new(
        "flag_key_uses_lap_record_id",
        DoctorSeverity::Error,
        "image_flags.flag_key must not depend on lap_record_id.",
        flag_key_count,
    );

    Ok(vec![
        missing_decision,
        missing_evidence,
        review_key_check,
        noncanonical_check,
        orphan_source_check,
        flag_key_check,
    ])
}

/// Mirrors `review_identity._canonical_key`: a NULL lap_index renders as an
/// empty segment and the driver name is re-normalized from
/// `driver_normalized or driver` with strip + casefold.
fn canonical_business_key_for_review(
    reason: &str,
    image_file_id: &str,
    lap_index: Option<i64>,
    driver_normalized: &str,
    source_file: &str,
    best_lap: &str,
) -> String {
    let lap_scoped = ["dirty_lap", "car", "driver_name"];
    let image_scoped = ["track", "weather", "race_class"];
    let lap_segment = lap_index.map(|i| i.to_string()).unwrap_or_default();

    if lap_scoped.contains(&reason) && !image_file_id.is_empty() {
        format!("{reason}:{image_file_id}:{lap_segment}")
    } else if image_scoped.contains(&reason) && !image_file_id.is_empty() {
        format!("{reason}:{image_file_id}")
    } else if !image_file_id.is_empty() || !driver_normalized.is_empty() {
        format!("{reason}:{image_file_id}:{lap_segment}:{driver_normalized}")
    } else {
        format!("{reason}:fallback:{source_file}:{driver_normalized}:{best_lap}")
    }
}

/// Python `_normalize`: strip + casefold (approximated with `to_lowercase`,
/// which the pipeline also uses when persisting normalized names).
fn normalize_identity_text(value: &str) -> String {
    value.trim().to_lowercase()
}

fn noncanonical_review_business_keys(conn: &Connection) -> Result<i64, DbError> {
    let mut stmt = conn.prepare(
        "SELECT reason, business_key, COALESCE(image_file_id, ''), lap_index,
                COALESCE(driver_normalized, ''), COALESCE(driver, ''),
                COALESCE(source_file, ''), COALESCE(best_lap, '')
         FROM review_cases",
    )?;
    let rows = stmt.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, Option<i64>>(3)?,
            row.get::<_, String>(4)?,
            row.get::<_, String>(5)?,
            row.get::<_, String>(6)?,
            row.get::<_, String>(7)?,
        ))
    })?;

    let mut count = 0i64;
    for row in rows {
        let (
            reason,
            business_key,
            image_file_id,
            lap_index,
            driver_normalized,
            driver,
            source_file,
            best_lap,
        ) = row?;
        // Python: _normalize(row.driver_normalized or row.driver) — an empty
        // normalized value falls back to the raw driver name.
        let normalized_source = if driver_normalized.is_empty() {
            &driver
        } else {
            &driver_normalized
        };
        let expected = canonical_business_key_for_review(
            &reason,
            &image_file_id,
            lap_index,
            &normalize_identity_text(normalized_source),
            &source_file,
            &best_lap,
        );
        if business_key != expected {
            count += 1;
        }
    }
    Ok(count)
}

fn review_parent_flag_checks(conn: &Connection) -> Result<Vec<DoctorCheck>, DbError> {
    let orphan_lap = scalar(
        conn,
        r#"
            SELECT COUNT(*) FROM review_cases
            WHERE lap_record_id IS NOT NULL
              AND lap_record_id NOT IN (SELECT id FROM lap_records)
        "#,
    )?;
    let orphan_lap_check = DoctorCheck::new(
        "review_cases_orphan_lap",
        DoctorSeverity::Error,
        "Review cases linked to missing lap rows.",
        orphan_lap,
    );

    let review_parent = check_sql(
        conn,
        "review_parent_mismatch",
        DoctorSeverity::Error,
        "Review run/source/result/lap links must describe one evidence chain.",
        r#"
            SELECT COUNT(*)
            FROM review_cases rc
            LEFT JOIN extraction_results er ON er.id = rc.extraction_result_id
            LEFT JOIN lap_records l ON l.id = rc.lap_record_id
            WHERE (
                rc.extraction_result_id IS NOT NULL
                AND (
                    er.id IS NULL
                    OR (rc.run_id IS NOT NULL AND rc.run_id IS NOT er.run_id)
                    OR (rc.image_file_id IS NOT NULL AND rc.image_file_id IS NOT er.image_file_id)
                )
            )
            OR (
                rc.lap_record_id IS NOT NULL
                AND (
                    l.id IS NULL
                    OR (rc.run_id IS NOT NULL AND rc.run_id IS NOT l.run_id)
                    OR (rc.image_file_id IS NOT NULL AND rc.image_file_id IS NOT l.image_file_id)
                    OR (
                        rc.extraction_result_id IS NOT NULL
                        AND rc.extraction_result_id IS NOT l.extraction_result_id
                    )
                )
            )
        "#,
    )?;

    let orphan_image = scalar(
        conn,
        r#"
            SELECT COUNT(*) FROM image_flags
            WHERE image_file_id NOT IN (SELECT id FROM image_files)
        "#,
    )?;
    let orphan_image_check = DoctorCheck::new(
        "flags_orphan_image",
        DoctorSeverity::Error,
        "Image flags linked to missing image files.",
        orphan_image,
    );

    let flag_parent = check_sql(
        conn,
        "flag_parent_mismatch",
        DoctorSeverity::Error,
        "Flag run/source/result/lap links must describe one evidence chain.",
        r#"
            SELECT COUNT(*)
            FROM image_flags f
            LEFT JOIN extraction_results er ON er.id = f.extraction_result_id
            LEFT JOIN lap_records l ON l.id = f.lap_record_id
            WHERE (
                f.extraction_result_id IS NOT NULL
                AND (
                    er.id IS NULL
                    OR (f.run_id IS NOT NULL AND f.run_id IS NOT er.run_id)
                    OR f.image_file_id IS NOT er.image_file_id
                )
            )
            OR (
                f.lap_record_id IS NOT NULL
                AND (
                    l.id IS NULL
                    OR (f.run_id IS NOT NULL AND f.run_id IS NOT l.run_id)
                    OR f.image_file_id IS NOT l.image_file_id
                    OR (
                        f.extraction_result_id IS NOT NULL
                        AND f.extraction_result_id IS NOT l.extraction_result_id
                    )
                )
            )
        "#,
    )?;

    let open_without_target = scalar(
        conn,
        "SELECT COUNT(*) FROM image_flags WHERE status = 'active' AND image_file_id IS NULL",
    )?;
    let open_without_target_check = DoctorCheck::new(
        "open_flags_without_target",
        DoctorSeverity::Warning,
        "Open flags without an image target.",
        open_without_target,
    );

    Ok(vec![
        orphan_lap_check,
        review_parent,
        orphan_image_check,
        flag_parent,
        open_without_target_check,
    ])
}

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

fn artifact_checks(conn: &Connection) -> Result<Vec<DoctorCheck>, DbError> {
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

// ── Schema drift checks (schema_checks.py) ───────────────────────────────────

const VOCABULARY_CHECKS: &[(&str, &str)] = &[
    ("image_files", "ck_image_files_file_status_vocab"),
    ("image_files", "ck_image_files_best_lap_status_vocab"),
    ("extraction_runs", "ck_extraction_runs_status_vocab"),
    ("extraction_runs", "ck_extraction_runs_mode_vocab"),
    ("run_inputs", "ck_run_inputs_decision_vocab"),
    ("run_inputs", "ck_run_inputs_duplicate_kind_vocab"),
    ("extraction_results", "ck_extraction_results_status_vocab"),
    ("extraction_attempts", "ck_extraction_attempts_status_vocab"),
    ("review_cases", "ck_review_cases_status_vocab"),
    ("review_cases", "ck_review_cases_outcome_vocab"),
    ("review_cases", "ck_review_cases_reason_vocab"),
    ("review_cases", "ck_review_cases_trigger_vocab"),
    ("review_cases", "ck_review_cases_decision_field_vocab"),
    ("image_flags", "ck_image_flags_status_vocab"),
    ("image_flags", "ck_image_flags_scope_vocab"),
    ("image_flags", "ck_image_flags_flag_type_vocab"),
    ("review_corrections", "ck_review_corrections_field_vocab"),
    ("review_corrections", "ck_review_corrections_cause_vocab"),
    (
        "external_record_imports",
        "ck_external_record_imports_status_vocab",
    ),
    (
        "external_lap_records",
        "ck_external_lap_records_weather_vocab",
    ),
];

const EXPECTED_SERVER_DEFAULTS: &[(&str, &[(&str, &str)])] = &[
    (
        "extraction_runs",
        &[
            ("status", "'pending'"),
            ("mode", "'normal'"),
            ("backend", "'lmstudio'"),
            ("workers", "1"),
            ("grayscale", "0"),
            ("total_inputs", "0"),
            ("to_process", "0"),
            ("processed", "0"),
            ("succeeded", "0"),
            ("failed", "0"),
            ("skipped", "0"),
            ("duplicate_count", "0"),
            ("review_case_count", "0"),
        ],
    ),
    (
        "image_files",
        &[
            ("race_datetime_source", "'file_modified_at'"),
            ("file_status", "'available'"),
            ("best_lap_status", "'pending'"),
        ],
    ),
    (
        "model_runtime_snapshots",
        &[("snapshot_kind", "'preflight'"), ("health_ok", "0")],
    ),
    ("extraction_results", &[("attempt_count", "0")]),
    ("extraction_attempts", &[("accepted", "0")]),
    ("model_artifacts", &[("is_canonical", "0")]),
    (
        "external_record_imports",
        &[
            ("total_rows", "0"),
            ("accepted_rows", "0"),
            ("rejected_rows", "0"),
            ("issue_count", "0"),
        ],
    ),
    (
        "lap_records",
        &[
            ("source_file", "''"),
            ("driver", "''"),
            ("driver_normalized", "''"),
            ("car", "''"),
            ("car_normalized", "''"),
            ("race_class", "''"),
            ("track", "''"),
            ("track_normalized", "''"),
            ("weather", "'unknown'"),
            ("best_lap", "''"),
            ("best_lap_ms", "0"),
            ("dirty", "0"),
            ("is_best_lap", "0"),
        ],
    ),
    (
        "review_cases",
        &[
            ("status", "'open'"),
            ("source_file", "''"),
            ("weather", "'unknown'"),
        ],
    ),
    ("review_corrections", &[("cause", "'unknown'")]),
    (
        "image_flags",
        &[
            ("flag_scope", "'image'"),
            ("status", "'active'"),
            ("created_by", "'system'"),
        ],
    ),
];

/// An in-memory database built from the shipped DDL constants, used as the
/// expected baseline for schema drift checks.
fn expected_schema_db() -> Result<Connection, DbError> {
    let conn = Connection::open_in_memory()?;
    for statement in TABLE_DDL {
        conn.execute_batch(statement)?;
    }
    for statement in INDEX_DDL {
        conn.execute_batch(statement)?;
    }
    Ok(conn)
}

const SCHEMA_OBJECTS_SQL: &str = "SELECT type, name, sql FROM sqlite_master
     WHERE type IN ('table', 'index', 'view')
       AND name NOT LIKE 'sqlite_%'
       AND name <> 'alembic_version'";

fn schema_objects(conn: &Connection) -> Result<BTreeMap<(String, String), String>, DbError> {
    let mut stmt = conn.prepare(SCHEMA_OBJECTS_SQL)?;
    let rows = stmt.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, Option<String>>(2)?,
        ))
    })?;
    let mut map = BTreeMap::new();
    for row in rows {
        let (kind, name, sql) = row?;
        map.insert((kind, name), normalize_schema_sql(sql.as_deref()));
    }
    Ok(map)
}

fn normalize_schema_sql(value: Option<&str>) -> String {
    match value {
        None => String::new(),
        Some(sql) => sql
            .split_whitespace()
            .collect::<Vec<_>>()
            .join(" ")
            .to_lowercase(),
    }
}

fn table_columns(conn: &Connection, table: &str) -> Result<Vec<String>, DbError> {
    let mut stmt = conn.prepare(&format!("PRAGMA table_info(\"{table}\")"))?;
    let rows = stmt.query_map([], |row| row.get::<_, String>(1))?;
    rows.collect::<Result<Vec<_>, _>>().map_err(DbError::from)
}

fn schema_drift_checks(conn: &Connection) -> Result<Vec<DoctorCheck>, DbError> {
    // Vocabulary constraints: every expected CHECK name must appear in the
    // stored CREATE TABLE statement.
    let mut vocabulary_missing = 0i64;
    {
        let mut stmt =
            conn.prepare("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?1")?;
        for (table_name, constraint_name) in VOCABULARY_CHECKS {
            let create_sql: Option<String> = stmt
                .query_row([table_name], |row| row.get(0))
                .unwrap_or(None);
            let present = create_sql
                .as_deref()
                .is_some_and(|sql| sql.contains(constraint_name));
            if !present {
                vocabulary_missing += 1;
            }
        }
    }
    let vocabulary_check = DoctorCheck::new(
        "vocabulary_check_constraints_missing",
        DoctorSeverity::Error,
        "SQLite schema must enforce clean-break vocabulary CHECK constraints.",
        vocabulary_missing,
    );

    // Column drift: compare actual columns against the in-memory baseline DB.
    let expected_conn = expected_schema_db()?;
    let expected_tables = {
        let mut stmt = expected_conn.prepare(
            "SELECT name FROM sqlite_master
             WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name <> 'alembic_version'",
        )?;
        let rows = stmt.query_map([], |row| row.get::<_, String>(0))?;
        rows.collect::<Result<Vec<_>, _>>()?
    };

    let mut column_drift = 0i64;
    for table in &expected_tables {
        let expected_columns = table_columns(&expected_conn, table)?;
        let actual_columns = table_columns(conn, table)?;
        let mut expected: Vec<&str> = expected_columns.iter().map(String::as_str).collect();
        let mut actual: Vec<&str> = actual_columns.iter().map(String::as_str).collect();
        expected.sort_unstable();
        actual.sort_unstable();
        column_drift += expected.iter().filter(|c| !actual.contains(c)).count() as i64;
        column_drift += actual.iter().filter(|c| !expected.contains(c)).count() as i64;
    }
    let column_drift_check = DoctorCheck::new(
        "schema_column_drift",
        DoctorSeverity::Error,
        "Effective SQLite columns must match the current DB vNext model.",
        column_drift,
    );

    // Server default drift: PRAGMA dflt_value must match the frozen contract.
    let mut default_drift = 0i64;
    for (table, defaults) in EXPECTED_SERVER_DEFAULTS {
        let mut stmt = conn.prepare(&format!("PRAGMA table_info(\"{table}\")"))?;
        let rows = stmt.query_map([], |row| {
            Ok((row.get::<_, String>(1)?, row.get::<_, Option<String>>(4)?))
        })?;
        let mut actual: BTreeMap<String, Option<String>> = BTreeMap::new();
        for row in rows {
            let (column, dflt) = row?;
            actual.insert(column, dflt);
        }
        for (column, default) in *defaults {
            if actual.get(*column).and_then(|v| v.as_deref()) != Some(*default) {
                default_drift += 1;
            }
        }
    }
    let default_drift_check = DoctorCheck::new(
        "schema_server_default_drift",
        DoctorSeverity::Error,
        "Effective SQLite server defaults must match the DB vNext contract.",
        default_drift,
    );

    // Frozen SQL drift: normalized sqlite_master entries must match baseline.
    let expected_objects = schema_objects(&expected_conn)?;
    let actual_objects = schema_objects(conn)?;
    let mut frozen_drift = 0i64;
    for key in expected_objects.keys().chain(actual_objects.keys()) {
        if expected_objects.get(key) != actual_objects.get(key) {
            frozen_drift += 1;
        }
    }
    let frozen_drift_check = DoctorCheck::new(
        "frozen_schema_sql_drift",
        DoctorSeverity::Error,
        "Effective tables, constraints, foreign keys, indexes, and views must match the frozen baseline SQL.",
        frozen_drift,
    );

    Ok(vec![
        vocabulary_check,
        column_drift_check,
        default_drift_check,
        frozen_drift_check,
    ])
}

// ── Orchestration ────────────────────────────────────────────────────────────

fn schema_head_check(schema_status: &str) -> Option<DoctorCheck> {
    if schema_status == "current" {
        None
    } else {
        Some(DoctorCheck::new(
            "schema_head",
            DoctorSeverity::Error,
            format!("schema state: {schema_status}"),
            1,
        ))
    }
}

/// Execute the basic doctor battery against an opened connection.
pub fn run_basic_checks(conn: &Connection) -> Result<DoctorReport, DbError> {
    let checks = vec![integrity_check(conn)?, foreign_key_check(conn)?];
    let version = user_version(conn)?;
    let status = schema_state_label(conn)?;
    Ok(DoctorReport {
        ok: checks.iter().all(|c| c.ok) && status == "current",
        schema_status: status,
        user_version: version,
        checks,
    }
    .finish())
}

fn schema_state_label(conn: &Connection) -> Result<String, DbError> {
    let count: i64 = conn.query_row(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",
        [],
        |row| row.get(0),
    )?;
    let version = user_version(conn)?;
    if count == 0 {
        Ok("empty".to_string())
    } else if version == SCHEMA_VERSION {
        Ok("current".to_string())
    } else if version < SCHEMA_VERSION {
        Ok("needs_upgrade".to_string())
    } else {
        Ok("newer_than_build".to_string())
    }
}

/// Convenience: open + check in one call.
pub fn doctor_on_path(path: &Path) -> Result<DoctorReport, DbError> {
    match schema_status(path)? {
        SchemaStatus::Empty => Ok(DoctorReport {
            ok: false,
            schema_status: "empty".to_string(),
            user_version: 0,
            checks: vec![DoctorCheck::new(
                "database_exists",
                DoctorSeverity::Error,
                "no database file or empty database",
                1,
            )],
        }),
        _ => {
            let conn = crate::open_connection(path)?;
            run_basic_checks(&conn)
        }
    }
}

/// Full doctor battery, matching the Python check order. A non-current schema
/// short-circuits to a single `schema_head` failure like `DbDoctorService`.
pub fn run_full_doctor(conn: &Connection, schema_status: String) -> Result<DoctorReport, DbError> {
    let version = user_version(conn)?;
    let Some(schema_head) = schema_head_check(&schema_status) else {
        let mut checks = Vec::new();
        checks.push(integrity_check(conn)?);
        checks.push(foreign_key_check(conn)?);
        checks.extend(run_counter_checks(conn)?);
        checks.push(invalid_status_values_check(conn)?);
        checks.extend(run_input_contract_checks(conn)?);
        checks.extend(image_file_checks(conn)?);
        checks.extend(run_input_process_checks(conn)?);
        checks.extend(artifact_checks(conn)?);
        checks.extend(review_core_checks(conn)?);
        checks.extend(best_lap_value_checks(conn)?);
        checks.extend(review_model_error_identity_checks(conn)?);
        checks.extend(lap_parent_checks(conn)?);
        checks.extend(review_parent_flag_checks(conn)?);
        checks.extend(best_lap_status_checks(conn)?);
        checks.extend(schema_drift_checks(conn)?);

        return Ok(DoctorReport {
            ok: false,
            schema_status,
            user_version: version,
            checks,
        }
        .finish());
    };

    Ok(DoctorReport {
        ok: false,
        schema_status,
        user_version: version,
        checks: vec![schema_head],
    }
    .finish())
}
