//! Read model backing the Image Debug surface — port of the Python
//! `GuiImageDebugReadQueries` (image_debug_reads.py).
//!
//! `list_image_debug_cases` mirrors the Python GUI list (one row per
//! `image_files`, ordered by `updated_at` DESC, limited). Per-image heavy
//! detail (raw response, JSON) is loaded only on selection.

#![allow(clippy::type_complexity)]

use rusqlite::{Connection, OptionalExtension};

use crate::error::DbError;

// ── Public projections ──────────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq)]
pub struct ImageDebugCase {
    pub image_file_id: String,
    pub image_name: String,
    pub race_date: Option<String>,
    pub file_status: String,
    pub processing_status: String,
    pub best_lap_status: String,
    pub latest_result_id: Option<String>,
    pub latest_result_status: Option<String>,
    pub run_id: Option<String>,
    pub backend: Option<String>,
    pub model: Option<String>,
    pub prompt_name: Option<String>,
    pub attempt_count: i64,
    pub lap_count: i64,
    pub review_count: i64,
    pub artifact_count: i64,
    pub created_at: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DebugExtraction {
    pub id: String,
    pub run_id: String,
    pub status: String,
    pub backend: Option<String>,
    pub model: Option<String>,
    pub prompt_name: Option<String>,
    pub accepted_attempt_id: Option<String>,
    pub attempt_count: i64,
    pub duration_ms: Option<i64>,
    pub input_tokens: Option<i64>,
    pub output_tokens: Option<i64>,
    pub total_tokens: Option<i64>,
    pub error_type: Option<String>,
    pub error_message: Option<String>,
    pub request_image_format: Option<String>,
    pub created_at: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DebugAttempt {
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
    pub created_at: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DebugLap {
    pub id: String,
    pub extraction_result_id: String,
    pub run_id: String,
    pub lap_index: i64,
    pub track: String,
    pub race_class: String,
    pub driver: String,
    pub car: String,
    pub best_lap: String,
    pub dirty: bool,
    pub is_best_lap: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DebugReview {
    pub id: String,
    pub case_number: i64,
    pub extraction_result_id: Option<String>,
    pub lap_record_id: Option<String>,
    pub status: String,
    pub reason: String,
    pub outcome: String,
    pub trigger: Option<String>,
    pub decision_field: Option<String>,
    pub model_value: Option<String>,
    pub corrected_value: Option<String>,
    pub current_track: Option<String>,
    pub current_race_class: Option<String>,
    pub current_best_lap: Option<String>,
    pub created_at: Option<String>,
}

/// Preflight runtime snapshot behind the selected result's run (powers the
/// Runtime tab; `None` when the run never reached preflight).
#[derive(Debug, Clone, PartialEq)]
pub struct DebugRuntimeSnapshot {
    pub endpoint: String,
    pub configured_model: Option<String>,
    pub loaded_model: Option<String>,
    pub instance_id: Option<String>,
    pub health_ok: bool,
    pub health_message: Option<String>,
    pub model_matches_config: Option<bool>,
    pub captured_at: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ImageDebugDetail {
    pub image_file_id: String,
    pub image_name: String,
    pub cases: Vec<ImageDebugCase>,
    pub results: Vec<DebugExtraction>,
    pub selected_result_id: Option<String>,
    pub attempts: Vec<DebugAttempt>,
    pub laps: Vec<DebugLap>,
    pub reviews: Vec<DebugReview>,
    pub raw_response: Option<String>,
    pub parsed_json: Option<String>,
    pub runtime_snapshot: Option<DebugRuntimeSnapshot>,
    pub timeline: Vec<String>,
}

// ── Helpers ─────────────────────────────────────────────────────────────

const PROCESSING_PROJECTION: &str = "COALESCE(\n        CASE\n            WHEN lr.status IS NULL THEN NULL\n            WHEN lr.status IN ('pending', 'running') THEN 'processing'\n            WHEN lr.status = 'ok' THEN 'processed_ok'\n            WHEN lr.status = 'cancelled' THEN 'cancelled'\n            ELSE 'processed_error'\n        END,\n        CASE WHEN li.image_file_id IS NOT NULL THEN 'skipped' END,\n        'unprocessed'\n    )";

fn count_by_image(
    conn: &Connection,
    table: &str,
    column: &str,
    ids: &[String],
) -> Result<std::collections::HashMap<String, i64>, DbError> {
    let mut out = std::collections::HashMap::new();
    // Chunked: one giant `IN (?,?,…)` past the SQLite variable limit fails
    // the whole query instead of degrading.
    for chunk in crate::id_chunks(ids) {
        if chunk.is_empty() {
            continue;
        }
        let placeholders = chunk.iter().map(|_| "?").collect::<Vec<_>>().join(",");
        let sql = format!(
            "SELECT {column}, COUNT(*) FROM {table} WHERE {column} IN ({placeholders}) GROUP BY {column}"
        );
        let mut stmt = conn.prepare(&sql)?;
        let params: Vec<&dyn rusqlite::types::ToSql> = chunk
            .iter()
            .map(|id| id as &dyn rusqlite::types::ToSql)
            .collect();
        let rows = stmt.query_map(params.as_slice(), |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)?))
        })?;
        for item in rows {
            let (k, v) = item?;
            out.insert(k, v);
        }
    }
    Ok(out)
}

// ── List ────────────────────────────────────────────────────────────────

/// List debug cases (one row per image, like the Python debug table).
/// Filters are applied in the app layer; this function fetches the raw
/// batch ordered by `updated_at` DESC, limited.
pub fn list_image_debug_cases(
    conn: &Connection,
    limit: i64,
) -> Result<Vec<ImageDebugCase>, DbError> {
    let mut stmt = conn.prepare(
        "SELECT id, current_name, semantic_name, file_status, best_lap_status,\n                CAST(race_date AS TEXT), CAST(updated_at AS TEXT), CAST(created_at AS TEXT)\n         FROM image_files ORDER BY updated_at DESC, id DESC LIMIT ?1",
    )?;
    let images: Vec<(
        String,
        Option<String>,
        Option<String>,
        String,
        String,
        Option<String>,
        Option<String>,
        Option<String>,
    )> = stmt
        .query_map([limit], |row| {
            Ok((
                row.get(0)?,
                row.get(1)?,
                row.get(2)?,
                row.get(3)?,
                row.get(4)?,
                row.get(5)?,
                row.get(6)?,
                row.get(7)?,
            ))
        })?
        .collect::<Result<Vec<_>, _>>()?;

    if images.is_empty() {
        return Ok(Vec::new());
    }
    let ids: Vec<String> = images.iter().map(|(id, ..)| id.clone()).collect();

    // Batch subqueries (mirror Python _cases_for_images).
    let processing = {
        let placeholders = ids.iter().map(|_| "?").collect::<Vec<_>>().join(",");
        let sql = format!(
            "SELECT i.id, {PROCESSING_PROJECTION}\n             FROM image_files i\n             LEFT JOIN (SELECT image_file_id, status, ROW_NUMBER() OVER (PARTITION BY image_file_id ORDER BY created_at DESC, id DESC) AS rk FROM extraction_results) lr ON lr.image_file_id = i.id AND lr.rk = 1\n             LEFT JOIN (SELECT ri.image_file_id FROM run_inputs ri JOIN (SELECT image_file_id, MAX(id) AS latest FROM run_inputs WHERE image_file_id IS NOT NULL GROUP BY image_file_id) l ON ri.id = l.latest WHERE ri.decision <> 'process') li ON li.image_file_id = i.id\n             WHERE i.id IN ({placeholders})"
        );
        let mut stmt = conn.prepare(&sql)?;
        let params: Vec<&dyn rusqlite::types::ToSql> = ids
            .iter()
            .map(|id| id as &dyn rusqlite::types::ToSql)
            .collect();
        let rows = stmt.query_map(params.as_slice(), |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
        })?;
        let mut map = std::collections::HashMap::new();
        for r in rows {
            let (k, v) = r?;
            map.insert(k, v);
        }
        map
    };

    let results_by_image = {
        let placeholders = ids.iter().map(|_| "?").collect::<Vec<_>>().join(",");
        let sql = format!(
            "SELECT image_file_id, id, run_id, status, model, attempt_count, error_type, error_message, request_image_format, backend, prompt_name, CAST(created_at AS TEXT)\n             FROM (SELECT r.image_file_id, r.id, r.run_id, r.status, r.model, r.attempt_count, r.error_type, r.error_message, r.request_image_format, run.backend, run.prompt_name, r.created_at, ROW_NUMBER() OVER (PARTITION BY r.image_file_id ORDER BY r.created_at DESC, r.id DESC) AS rk FROM extraction_results r LEFT JOIN extraction_runs run ON run.id = r.run_id WHERE r.image_file_id IN ({placeholders})) WHERE rk = 1"
        );
        // Simpler: one latest row per image via window.
        let mut stmt = conn.prepare(&sql)?;
        let params: Vec<&dyn rusqlite::types::ToSql> = ids
            .iter()
            .map(|id| id as &dyn rusqlite::types::ToSql)
            .collect();
        // Fallback when the join introduces NULLs for prompt/backend: fetch per image individually if the bulk query is empty.
        let mut map: std::collections::HashMap<
            String,
            (
                String,
                String,
                String,
                Option<String>,
                i64,
                Option<String>,
                Option<String>,
                Option<String>,
                Option<String>,
                Option<String>,
                Option<String>,
            ),
        > = std::collections::HashMap::new();
        let rows = stmt.query_map(params.as_slice(), |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, Option<String>>(4)?,
                row.get::<_, i64>(5)?,
                row.get::<_, Option<String>>(6)?,
                row.get::<_, Option<String>>(7)?,
                row.get::<_, Option<String>>(8)?,
                row.get::<_, Option<String>>(9)?,
                row.get::<_, Option<String>>(10)?,
                row.get::<_, Option<String>>(11)?,
            ))
        })?;
        for r in rows {
            let (
                image_id,
                id,
                run_id,
                status,
                model,
                attempt_count,
                error_type,
                error_message,
                req_fmt,
                backend,
                prompt,
                created,
            ) = r?;
            map.insert(
                image_id,
                (
                    id,
                    run_id,
                    status,
                    model,
                    attempt_count,
                    error_type,
                    error_message,
                    req_fmt,
                    backend,
                    prompt,
                    created,
                ),
            );
        }
        map
    };

    let lap_counts = count_by_image(conn, "lap_records", "image_file_id", &ids)?;
    let review_counts = count_by_image(conn, "review_cases", "image_file_id", &ids)?;
    let artifact_counts =
        count_by_image(conn, "model_artifacts", "image_file_id", &ids).unwrap_or_default();

    let mut cases = Vec::new();
    for (
        id,
        current_name,
        semantic_name,
        file_status,
        best_lap_status,
        race_date,
        updated_at,
        created_at,
    ) in images
    {
        let name = current_name.or(semantic_name).unwrap_or_else(|| id.clone());
        let latest = results_by_image.get(&id);
        cases.push(ImageDebugCase {
            image_file_id: id.clone(),
            image_name: name,
            race_date: race_date.clone(),
            file_status: file_status.clone(),
            processing_status: processing
                .get(&id)
                .cloned()
                .unwrap_or_else(|| "unprocessed".into()),
            best_lap_status,
            latest_result_id: latest.as_ref().map(|(rid, ..)| rid.clone()),
            latest_result_status: latest.as_ref().map(|(_, _, status, ..)| status.clone()),
            run_id: latest.as_ref().map(|(_, run_id, ..)| run_id.clone()),
            backend: latest
                .as_ref()
                .and_then(|(_, _, _, _, _, _, _, _, backend, ..)| backend.clone()),
            model: latest
                .as_ref()
                .and_then(|(_, _, _, model, ..)| model.clone()),
            prompt_name: latest
                .as_ref()
                .and_then(|(_, _, _, _, _, _, _, _, _, prompt, ..)| prompt.clone()),
            attempt_count: latest.as_ref().map(|(_, _, _, _, c, ..)| *c).unwrap_or(0),
            lap_count: lap_counts.get(&id).copied().unwrap_or(0),
            review_count: review_counts.get(&id).copied().unwrap_or(0),
            artifact_count: artifact_counts.get(&id).copied().unwrap_or(0),
            created_at: updated_at.or(created_at),
        });
    }
    Ok(cases)
}

// ── Detail ──────────────────────────────────────────────────────────────

/// Detail for one image. `selected_result_id` picks which extraction result's
/// attempts/raw evidence to surface (the Python `selected_result_id`
/// contract); when `None` the most recent result wins.
pub fn get_image_debug_detail(
    conn: &Connection,
    image_file_id: &str,
    selected_result_id: Option<&str>,
) -> Result<Option<ImageDebugDetail>, DbError> {
    let image_row: Option<(
        String,
        Option<String>,
        Option<String>,
        String,
        String,
        Option<String>,
        Option<String>,
    )> = {
        let mut stmt = conn.prepare(
            "SELECT id, current_name, semantic_name, file_status, best_lap_status, CAST(updated_at AS TEXT), CAST(created_at AS TEXT) FROM image_files WHERE id = ?1",
        )?;
        let mut rows = stmt.query_map([image_file_id], |row| {
            Ok((
                row.get(0)?,
                row.get::<_, Option<String>>(1)?,
                row.get::<_, Option<String>>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, String>(4)?,
                row.get::<_, Option<String>>(5)?,
                row.get::<_, Option<String>>(6)?,
            ))
        })?;
        match rows.next() {
            Some(r) => Some(r?),
            None => None,
        }
    };
    let Some((
        id,
        current_name,
        semantic_name,
        _file_status,
        _best_lap_status,
        _updated_at,
        _created_at,
    )) = image_row
    else {
        return Ok(None);
    };
    let image_name = current_name
        .clone()
        .or(semantic_name.clone())
        .unwrap_or_else(|| id.clone());

    // All results for this image (newest first).
    let mut stmt = conn.prepare(
        "SELECT r.id, r.run_id, r.status, r.model, r.attempt_count, r.error_type, r.error_message, r.request_image_format, COALESCE(run.backend, ''), COALESCE(run.prompt_name, ''), CAST(r.created_at AS TEXT), r.accepted_attempt_id, r.input_tokens, r.output_tokens, r.total_tokens, r.duration_ms\n         FROM extraction_results r LEFT JOIN extraction_runs run ON run.id = r.run_id WHERE r.image_file_id = ?1 ORDER BY r.created_at DESC, r.id DESC",
    )?;
    let results: Vec<DebugExtraction> = stmt
        .query_map([image_file_id], |row| {
            Ok(DebugExtraction {
                id: row.get(0)?,
                run_id: row.get(1)?,
                status: row.get(2)?,
                model: row.get::<_, Option<String>>(3)?,
                attempt_count: row.get(4)?,
                error_type: row.get::<_, Option<String>>(5)?,
                error_message: row.get::<_, Option<String>>(6)?,
                request_image_format: row.get::<_, Option<String>>(7)?,
                backend: {
                    let v: String = row.get(8)?;
                    if v.is_empty() { None } else { Some(v) }
                },
                prompt_name: {
                    let v: String = row.get(9)?;
                    if v.is_empty() { None } else { Some(v) }
                },
                created_at: row.get::<_, Option<String>>(10)?,
                accepted_attempt_id: row.get::<_, Option<String>>(11)?,
                input_tokens: row.get::<_, Option<i64>>(12)?,
                output_tokens: row.get::<_, Option<i64>>(13)?,
                total_tokens: row.get::<_, Option<i64>>(14)?,
                duration_ms: row.get::<_, Option<i64>>(15)?,
            })
        })?
        .collect::<Result<Vec<_>, _>>()?;

    let selected = match selected_result_id {
        Some(req) => results.iter().find(|r| r.id == req).or(results.first()),
        None => results.first(),
    };
    let selected_id = selected.map(|r| r.id.clone());

    // Attempts for the selected result only (like the Python detail).
    let attempts: Vec<DebugAttempt> = if let Some(sid) = &selected_id {
        let mut stmt = conn.prepare(
            "SELECT id, extraction_result_id, attempt_number, attempt_reason, status, accepted, rejected_reason, model, duration_ms, total_tokens, tokens_per_second, parse_error, validation_status, CAST(created_at AS TEXT) FROM extraction_attempts WHERE extraction_result_id = ?1 ORDER BY attempt_number ASC",
        )?;
        stmt.query_map([sid.as_str()], |row| {
            Ok(DebugAttempt {
                id: row.get(0)?,
                extraction_result_id: row.get(1)?,
                attempt_number: row.get(2)?,
                attempt_reason: row.get(3)?,
                status: row.get(4)?,
                accepted: row.get::<_, i64>(5)? != 0,
                rejected_reason: row.get::<_, Option<String>>(6)?,
                model: row.get::<_, Option<String>>(7)?,
                duration_ms: row.get::<_, Option<i64>>(8)?,
                total_tokens: row.get::<_, Option<i64>>(9)?,
                tokens_per_second: row.get::<_, Option<f64>>(10)?,
                parse_error: row.get::<_, Option<String>>(11)?,
                validation_status: row.get::<_, Option<String>>(12)?,
                created_at: row.get::<_, Option<String>>(13)?,
            })
        })?
        .collect::<Result<Vec<_>, _>>()?
    } else {
        Vec::new()
    };

    // Laps for this image (all runs).
    let mut stmt = conn.prepare(
        "SELECT id, extraction_result_id, run_id, lap_index, track, race_class, driver, car, best_lap, dirty, is_best_lap FROM lap_records WHERE image_file_id = ?1 ORDER BY lap_index ASC",
    )?;
    let laps: Vec<DebugLap> = stmt
        .query_map([image_file_id], |row| {
            Ok(DebugLap {
                id: row.get(0)?,
                extraction_result_id: row.get(1)?,
                run_id: row.get(2)?,
                lap_index: row.get(3)?,
                track: row.get(4)?,
                race_class: row.get(5)?,
                driver: row.get(6)?,
                car: row.get(7)?,
                best_lap: row.get(8)?,
                dirty: row.get::<_, i64>(9)? != 0,
                is_best_lap: row.get::<_, i64>(10)? != 0,
            })
        })?
        .collect::<Result<Vec<_>, _>>()?;

    let mut stmt = conn.prepare(
        "SELECT id, case_number, extraction_result_id, lap_record_id, status, reason, outcome, \"trigger\", decision_field, model_value, corrected_value, track, race_class, best_lap, CAST(created_at AS TEXT) FROM review_cases WHERE image_file_id = ?1 ORDER BY case_number ASC",
    )?;
    let reviews: Vec<DebugReview> = stmt
        .query_map([image_file_id], |row| {
            Ok(DebugReview {
                id: row.get(0)?,
                case_number: row.get(1)?,
                extraction_result_id: row.get::<_, Option<String>>(2)?,
                lap_record_id: row.get::<_, Option<String>>(3)?,
                status: row.get(4)?,
                reason: row.get(5)?,
                outcome: row.get::<_, Option<String>>(6)?.unwrap_or_default(),
                trigger: row.get::<_, Option<String>>(7)?,
                decision_field: row.get::<_, Option<String>>(8)?,
                model_value: row.get::<_, Option<String>>(9)?,
                corrected_value: row.get::<_, Option<String>>(10)?,
                current_track: row.get::<_, Option<String>>(11)?,
                current_race_class: row.get::<_, Option<String>>(12)?,
                current_best_lap: row.get::<_, Option<String>>(13)?,
                created_at: row.get::<_, Option<String>>(14)?,
            })
        })?
        .collect::<Result<Vec<_>, _>>()?;

    // Raw evidence: accepted/first attempt's raw_response, plus parsed_json.
    let (raw_response, parsed_json) = if let Some(att) =
        attempts.iter().find(|a| a.accepted).or(attempts.first())
    {
        let mut stmt = conn
            .prepare("SELECT raw_response, parsed_json FROM extraction_attempts WHERE id = ?1")?;
        let row: Option<(Option<String>, Option<String>)> = stmt
            .query_row([att.id.as_str()], |row| Ok((row.get(0)?, row.get(1)?)))
            .ok();
        row.unwrap_or((None, None))
    } else {
        (None, None)
    };

    let timeline = build_timeline(&image_name, &results, &attempts, &laps, &reviews);

    // One-row cases list for the header title area (single image).
    // NOTE: never derive this from `list_image_debug_cases(conn, 1)` — that
    // fetches only the globally most-recent image, leaving `cases` silently
    // empty for every other image. Build the row from this image's own data.
    let latest = results.first();
    let artifact_count: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM model_artifacts WHERE image_file_id = ?1",
            [image_file_id],
            |r| r.get(0),
        )
        .unwrap_or(0);
    let processing_status = latest
        .map(|r| match r.status.as_str() {
            "pending" | "running" => "processing".to_string(),
            "ok" => "processed_ok".to_string(),
            "cancelled" => "cancelled".to_string(),
            _ => "processed_error".to_string(),
        })
        .unwrap_or_else(|| "unprocessed".to_string());
    let cases = vec![ImageDebugCase {
        image_file_id: id.clone(),
        image_name: image_name.clone(),
        race_date: None,
        file_status: _file_status.clone(),
        processing_status,
        best_lap_status: _best_lap_status.clone(),
        latest_result_id: latest.map(|r| r.id.clone()),
        latest_result_status: latest.map(|r| r.status.clone()),
        run_id: latest.map(|r| r.run_id.clone()),
        backend: latest.and_then(|r| r.backend.clone()),
        model: latest.and_then(|r| r.model.clone()),
        prompt_name: latest.and_then(|r| r.prompt_name.clone()),
        attempt_count: latest.map(|r| r.attempt_count).unwrap_or(0),
        lap_count: laps.len() as i64,
        review_count: reviews.len() as i64,
        artifact_count,
        created_at: _created_at.clone().or(_updated_at.clone()),
    }];

    // Preflight runtime snapshot behind the selected result's run (the
    // Runtime tab used to claim "No runtime snapshot linked" unconditionally
    // even though every run persists one).
    let runtime_snapshot: Option<DebugRuntimeSnapshot> =
        selected.map(|r| r.run_id.clone()).and_then(|run_id| {
            conn.query_row(
                "SELECT endpoint, configured_model, loaded_model, instance_id,
                        health_ok, health_message, model_matches_config,
                        CAST(captured_at AS TEXT)
                 FROM model_runtime_snapshots
                 WHERE run_id = ?1 AND snapshot_kind = 'preflight' LIMIT 1",
                [&run_id],
                |row| {
                    Ok(DebugRuntimeSnapshot {
                        endpoint: row.get(0)?,
                        configured_model: row.get(1)?,
                        loaded_model: row.get(2)?,
                        instance_id: row.get(3)?,
                        health_ok: row.get::<_, i64>(4)? != 0,
                        health_message: row.get(5)?,
                        model_matches_config: row.get::<_, Option<i64>>(6)?.map(|v| v != 0),
                        captured_at: row.get(7)?,
                    })
                },
            )
            .optional()
            .unwrap_or(None)
        });

    Ok(Some(ImageDebugDetail {
        image_file_id: id.clone(),
        image_name: image_name.clone(),
        cases,
        results,
        selected_result_id: selected_id,
        attempts,
        laps,
        reviews,
        raw_response,
        parsed_json,
        runtime_snapshot,
        timeline,
    }))
}

/// Resolve by result id straight to its owning image.
pub fn get_image_debug_detail_by_result(
    conn: &Connection,
    extraction_result_id: &str,
) -> Result<Option<ImageDebugDetail>, DbError> {
    let image_file_id: String = match conn.query_row(
        "SELECT image_file_id FROM extraction_results WHERE id = ?1",
        [extraction_result_id],
        |row| row.get(0),
    ) {
        Ok(v) => v,
        Err(rusqlite::Error::QueryReturnedNoRows) => return Ok(None),
        Err(e) => return Err(DbError::from(e)),
    };
    get_image_debug_detail(conn, &image_file_id, Some(extraction_result_id))
}

fn build_timeline(
    image_name: &str,
    results: &[DebugExtraction],
    attempts: &[DebugAttempt],
    laps: &[DebugLap],
    reviews: &[DebugReview],
) -> Vec<String> {
    let mut events: Vec<(String, String)> = Vec::new();
    events.push(("".into(), format!("image registered · {image_name}")));
    for r in results {
        let stamp = r.created_at.clone().unwrap_or_default();
        events.push((stamp, format!("result {} · {}", r.status, r.id)));
    }
    for a in attempts {
        let stamp = a.created_at.clone().unwrap_or_default();
        let suffix = if a.accepted {
            "accepted"
        } else {
            a.status.as_str()
        };
        events.push((stamp, format!("attempt #{} · {}", a.attempt_number, suffix)));
    }
    for l in laps {
        events.push((
            "".into(),
            format!("lap #{} · {} · {}", l.lap_index, l.track, l.best_lap),
        ));
    }
    for rev in reviews {
        let stamp = rev.created_at.clone().unwrap_or_default();
        events.push((
            stamp,
            format!(
                "review #{} · {} · {}",
                rev.case_number, rev.status, rev.reason
            ),
        ));
    }
    events.sort_by(|a, b| a.0.cmp(&b.0));
    events.into_iter().map(|(_, m)| m).collect()
}
