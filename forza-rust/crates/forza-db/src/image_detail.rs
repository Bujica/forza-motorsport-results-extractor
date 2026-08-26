//! Read queries backing the Image Detail surface (GUI detail path).
//!
//! Mirrors the operator-facing projections of the Python `GuiReadService`
//! (`get_image`, `list_laps(image_file_id=…)`, `list_review_queue`,
//! `list_extraction_results`, `list_extraction_attempts`). Raw response
//! bodies and JSON payloads are intentionally NOT loaded here — they belong
//! to Image Debug, per the GUI contract's list/detail policy.

use crate::error::DbError;
use rusqlite::{Connection, Row};

/// Metadata projection for one image file (plus derived processing status).
#[derive(Debug, Clone, PartialEq)]
pub struct ImageDetailMeta {
    pub id: String,
    pub file_hash: String,
    pub duplicate_of_image_file_id: Option<String>,
    pub current_name: Option<String>,
    pub semantic_name: Option<String>,
    pub current_path: Option<String>,
    pub file_status: String,
    pub best_lap_status: String,
    pub processing_status: String,
    pub size_bytes: Option<i64>,
    pub width_px: Option<i64>,
    pub height_px: Option<i64>,
    pub bit_depth: Option<i64>,
    pub color_mode: Option<String>,
    pub mime_type: Option<String>,
    pub image_format: Option<String>,
    pub race_date: Option<String>,
    pub race_datetime_source: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DetailLapRow {
    pub id: String,
    pub lap_index: i64,
    pub track: String,
    pub race_class: String,
    pub weather: String,
    pub temp_f: Option<f64>,
    pub driver: String,
    pub car: String,
    pub best_lap: String,
    pub best_lap_ms: i64,
    pub dirty: bool,
    pub is_best_lap: bool,
    pub source_file: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DetailResultRow {
    pub id: String,
    pub run_id: String,
    pub status: String,
    pub error_message: Option<String>,
    pub backend: Option<String>,
    pub model: Option<String>,
    pub prompt_name: Option<String>,
    pub attempt_count: i64,
    pub duration_ms: Option<i64>,
    pub total_tokens: Option<i64>,
    pub tokens_per_second: Option<f64>,
    pub created_at: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DetailAttemptRow {
    pub id: String,
    pub extraction_result_id: String,
    pub attempt_number: i64,
    pub attempt_reason: String,
    pub status: String,
    pub accepted: bool,
    pub rejected_reason: Option<String>,
    pub model: Option<String>,
    pub duration_ms: Option<i64>,
    pub total_tokens: Option<i64>,
    pub tokens_per_second: Option<f64>,
    pub parse_error: Option<String>,
    pub validation_status: Option<String>,
    pub created_at: String,
}

const PROCESSING_PROJECTION: &str = "
    COALESCE(
        CASE
            WHEN lr.status IS NULL THEN NULL
            WHEN lr.status IN ('pending', 'running') THEN 'processing'
            WHEN lr.status = 'ok' THEN 'processed_ok'
            WHEN lr.status = 'cancelled' THEN 'cancelled'
            ELSE 'processed_error'
        END,
        CASE WHEN li.image_file_id IS NOT NULL THEN 'skipped' END,
        'unprocessed'
    )
";

fn meta_row(row: &Row<'_>) -> rusqlite::Result<ImageDetailMeta> {
    Ok(ImageDetailMeta {
        id: row.get(0)?,
        file_hash: row.get(1)?,
        duplicate_of_image_file_id: row.get(2)?,
        current_name: row.get(3)?,
        semantic_name: row.get(4)?,
        current_path: row.get(5)?,
        file_status: row.get(6)?,
        best_lap_status: row.get(7)?,
        processing_status: row.get(8)?,
        size_bytes: row.get(9)?,
        width_px: row.get(10)?,
        height_px: row.get(11)?,
        bit_depth: row.get(12)?,
        color_mode: row.get(13)?,
        mime_type: row.get(14)?,
        image_format: row.get(15)?,
        race_date: row.get(16)?,
        race_datetime_source: row.get(17)?,
    })
}

/// Load one image with the same derived processing status as the inventory.
pub fn image_detail_meta(
    conn: &Connection,
    image_file_id: &str,
) -> Result<Option<ImageDetailMeta>, DbError> {
    let sql = format!(
        "SELECT i.id, i.file_hash, i.duplicate_of_image_file_id,
                i.current_name, i.semantic_name, i.current_path,
                i.file_status, i.best_lap_status,
                {PROCESSING_PROJECTION},
                i.size_bytes, i.width_px, i.height_px, i.bit_depth,
                i.color_mode, i.mime_type, i.image_format,
                CAST(i.race_date AS TEXT), i.race_datetime_source
         FROM image_files i
         LEFT JOIN (
             SELECT image_file_id, status,
                    ROW_NUMBER() OVER (
                        PARTITION BY image_file_id
                        ORDER BY created_at DESC, id DESC
                    ) AS result_rank
             FROM extraction_results
             WHERE image_file_id IS NOT NULL
         ) lr ON lr.image_file_id = i.id AND lr.result_rank = 1
         LEFT JOIN (
             SELECT ri.image_file_id
             FROM run_inputs ri
             JOIN (
                 SELECT image_file_id, MAX(id) AS latest_input_id
                 FROM run_inputs
                 WHERE image_file_id IS NOT NULL
                 GROUP BY image_file_id
             ) l ON ri.id = l.latest_input_id
             WHERE ri.decision <> 'process'
         ) li ON li.image_file_id = i.id
         WHERE i.id = ?1"
    );
    let mut stmt = conn.prepare(&sql)?;
    let mut rows = stmt.query_map([image_file_id], meta_row)?;
    match rows.next() {
        Some(row) => Ok(Some(row?)),
        None => Ok(None),
    }
}

/// Lap rows for the Laps tab (lap_index order).
pub fn laps_for_image(
    conn: &Connection,
    image_file_id: &str,
) -> Result<Vec<DetailLapRow>, DbError> {
    let sql = "
        SELECT id, lap_index, track, race_class, weather, temp_f,
               driver, car, best_lap, best_lap_ms, dirty, is_best_lap,
               source_file
        FROM lap_records
        WHERE image_file_id = ?1
        ORDER BY lap_index";
    let mut stmt = conn.prepare(sql)?;
    let rows = stmt
        .query_map([image_file_id], |row| {
            Ok(DetailLapRow {
                id: row.get(0)?,
                lap_index: row.get(1)?,
                track: row.get(2)?,
                race_class: row.get(3)?,
                weather: row.get(4)?,
                temp_f: row.get(5)?,
                driver: row.get(6)?,
                car: row.get(7)?,
                best_lap: row.get(8)?,
                best_lap_ms: row.get(9)?,
                dirty: row.get::<_, i64>(10)? != 0,
                is_best_lap: row.get::<_, i64>(11)? != 0,
                source_file: row.get(12)?,
            })
        })?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(rows)
}

/// Extraction result summaries for the Extractions tab (created_at DESC).
pub fn results_for_image(
    conn: &Connection,
    image_file_id: &str,
) -> Result<Vec<DetailResultRow>, DbError> {
    let sql = "
        SELECT r.id, r.run_id, r.status, r.error_message,
               COALESCE(run.backend, ''), r.model,
               COALESCE(run.prompt_name, ''),
               r.attempt_count, r.duration_ms, r.total_tokens,
               r.tokens_per_second,
               COALESCE(CAST(r.created_at AS TEXT), '')
        FROM extraction_results r
        LEFT JOIN extraction_runs run ON run.id = r.run_id
        WHERE r.image_file_id = ?1
        ORDER BY r.created_at DESC, r.id DESC";
    let mut stmt = conn.prepare(sql)?;
    let rows = stmt
        .query_map([image_file_id], |row| {
            Ok(DetailResultRow {
                id: row.get(0)?,
                run_id: row.get(1)?,
                status: row.get(2)?,
                error_message: row.get(3)?,
                backend: row.get(4)?,
                model: row.get(5)?,
                prompt_name: row.get(6)?,
                attempt_count: row.get(7)?,
                duration_ms: row.get(8)?,
                total_tokens: row.get(9)?,
                tokens_per_second: row.get(10)?,
                created_at: row.get(11)?,
            })
        })?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(rows)
}

/// Attempt summaries for the Attempts tab (created_at DESC, number ASC —
/// same ordering as `list_extraction_attempts`).
pub fn attempts_for_image(
    conn: &Connection,
    image_file_id: &str,
) -> Result<Vec<DetailAttemptRow>, DbError> {
    let sql = "
        SELECT id, extraction_result_id, attempt_number, attempt_reason,
               status, accepted, rejected_reason, model, duration_ms,
               total_tokens, tokens_per_second, parse_error,
               validation_status,
               COALESCE(CAST(created_at AS TEXT), '')
        FROM extraction_attempts
        WHERE image_file_id = ?1
        ORDER BY created_at DESC, attempt_number ASC";
    let mut stmt = conn.prepare(sql)?;
    let rows = stmt
        .query_map([image_file_id], |row| {
            Ok(DetailAttemptRow {
                id: row.get(0)?,
                extraction_result_id: row.get(1)?,
                attempt_number: row.get(2)?,
                attempt_reason: row.get(3)?,
                status: row.get(4)?,
                accepted: row.get::<_, i64>(5)? != 0,
                rejected_reason: row.get(6)?,
                model: row.get(7)?,
                duration_ms: row.get(8)?,
                total_tokens: row.get(9)?,
                tokens_per_second: row.get(10)?,
                parse_error: row.get(11)?,
                validation_status: row.get(12)?,
                created_at: row.get(13)?,
            })
        })?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(rows)
}
