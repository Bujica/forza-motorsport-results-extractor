//! Extraction replay: run a recorded model response through the full
//! pipeline — parse, validate, persist attempts/result/laps — without
//! contacting LM Studio (Fase 7 acceptance criterion).

use rusqlite::Connection;

use forza_db::repositories::runs::{
    AttemptInsert, ResultStats, finalize_result_ok, insert_attempt_full,
};
use forza_domain::lap::{
    RawGridEntry, detect_race_class, is_dirty_lap, normalize_weather, parse_lap_time_ms,
    sanitize_driver_name, strip_dirty_symbol,
};
use forza_lmstudio::protocol::{AttemptStatus, ModelAttemptRecord};
use forza_lmstudio::response::{parse_and_validate_response, semantic_retry_issues};

/// Convert a backend record into the persistence primitive.
pub fn to_attempt_insert<'a>(record: &'a ModelAttemptRecord, model: &'a str) -> AttemptInsert<'a> {
    AttemptInsert {
        attempt_number: record.attempt_number,
        attempt_reason: &record.attempt_reason,
        status: match record.status {
            forza_lmstudio::protocol::AttemptStatus::Ok => "ok",
            forza_lmstudio::protocol::AttemptStatus::Error => "error",
        },
        accepted: record.accepted,
        rejected_reason: record.rejected_reason.as_deref(),
        model: Some(model),
        model_instance_id: record.model_instance_id.as_deref(),
        http_status: record.http_status,
        error_code: record.error_code.as_deref(),
        error_message: record.error_message.as_deref(),
        request_image_format: None,
        request_image_mime_type: None,
        request_image_width: None,
        request_image_height: None,
        request_image_bytes: None,
        context_length: Some(5000),
        reasoning_mode: Some("off"),
        request_config_json: record.request_config_json.as_deref(),
        request_messages_json: record.request_messages_json.as_deref(),
        request_hash: record.request_hash.as_deref(),
        runtime_snapshot_id: None,
        retry_instruction_text: record.retry_instruction_text.as_deref(),
        raw_response: record.raw_response.as_deref(),
        parsed_json: record.parsed_json.as_deref(),
        parse_error: record.parse_error.as_deref(),
        validation_status: record.validation_status.as_deref(),
        validation_issues_json: record.validation_issues_json.as_deref(),
        response_stats_json: record.response_stats_json.as_deref(),
        duration_ms: record.duration_ms,
        input_tokens: record.input_tokens,
        output_tokens: record.output_tokens,
        reasoning_tokens: record.reasoning_tokens,
        total_tokens: record.total_tokens,
        tokens_per_second: record.tokens_per_second,
        time_to_first_token_s: record.time_to_first_token_s,
        model_load_time_s: record.model_load_time_s,
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct ReplayOutcome {
    pub accepted: bool,
    pub lap_rows: usize,
    pub attempt_row_ids: Vec<String>,
}

/// Persist one recorded response for `image_file_id` under `run_id`.
///
/// Steps: strict parse+validate → per-attempt rows → finalize result →
/// derive lap records from the parsed entries using the embedded reference
/// normalizers.
pub fn replay_recorded_response(
    conn: &mut Connection,
    run_id: &str,
    image_file_id: &str,
    extraction_result_id: &str,
    raw_response: &str,
    model: &str,
) -> Result<ReplayOutcome, String> {
    let parsed = parse_and_validate_response(raw_response)?;
    let issues = semantic_retry_issues(&parsed);

    let mut attempt_row_ids = Vec::new();
    // The caller supplies a single recorded response; model it as attempt #1.
    let record = ModelAttemptRecord {
        attempt_number: 1,
        attempt_reason: "initial".into(),
        status: AttemptStatus::Ok,
        accepted: true,
        raw_response: Some(raw_response.to_string()),
        parsed_json: Some(parsed.to_string()),
        validation_status: Some(if issues.is_empty() {
            "accepted".into()
        } else {
            "accepted_with_issues".into()
        }),
        validation_issues_json: (!issues.is_empty()).then(|| serde_json::json!(issues).to_string()),
        ..Default::default()
    };
    let insert = to_attempt_insert(&record, model);
    let attempt_row_id =
        insert_attempt_full(conn, run_id, image_file_id, extraction_result_id, &insert)
            .map_err(|e| format!("insert attempt: {e}"))?;
    attempt_row_ids.push(attempt_row_id.clone());

    let stats = ResultStats {
        model: Some(model),
        model_instance_id: record.model_instance_id.as_deref(),
        input_tokens: record.input_tokens,
        output_tokens: record.output_tokens,
        reasoning_tokens: record.reasoning_tokens,
        total_tokens: record.total_tokens,
        tokens_per_second: record.tokens_per_second,
        time_to_first_token_s: record.time_to_first_token_s,
        model_load_time_s: record.model_load_time_s,
        duration_ms: record.duration_ms,
    };
    finalize_result_ok(conn, extraction_result_id, &attempt_row_id, 1, &stats)
        .map_err(|e| e.to_string())?;

    // Derive laps from parsed entries (shared with the live extraction path).
    let lap_rows = derive_and_insert_laps(
        conn,
        run_id,
        image_file_id,
        extraction_result_id,
        &parsed,
        None,
    )?;

    Ok(ReplayOutcome {
        accepted: true,
        lap_rows,
        attempt_row_ids,
    })
}

/// Insert lap records derived from a validated parsed response.
/// Shared by the recorded-replay and the live extraction paths.
pub fn derive_and_insert_laps(
    conn: &Connection,
    run_id: &str,
    image_file_id: &str,
    extraction_result_id: &str,
    parsed: &serde_json::Value,
    source_file: Option<&str>,
) -> Result<usize, String> {
    let refs = forza_domain::reference_data::embedded_reference_data();
    let track_raw = parsed.get("t").and_then(|v| v.as_str()).unwrap_or("");
    let track_fixed = if track_raw.is_empty() {
        "Unknown".to_string()
    } else {
        match forza_domain::normalizer::fix_track_name(track_raw, &refs) {
            Some(track) => track,
            None => format!("Unknown (ambiguous layout): {track_raw}"),
        }
    };
    let weather = normalize_weather(parsed.get("w").and_then(|v| v.as_str()));
    let temp_f = parsed.get("tf").and_then(|v| v.as_f64());

    let entries = parsed
        .get("e")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    // Python's process_image() builds the corrected grid only from entries
    // with a valid lap time. Invalid/empty `bl` rows never reach lap_records
    // and must not influence session-class detection either.
    let mut valid_entries = Vec::new();
    for entry in &entries {
        let car_raw = entry.get("ca").and_then(|v| v.as_str()).unwrap_or("");
        let class_field = entry.get("cl").and_then(|v| v.as_str());
        let car = forza_domain::normalizer::fix_car_name(car_raw, &refs);
        let best_lap_str = entry.get("bl").and_then(|v| v.as_str());
        let best_lap_ms = best_lap_str.and_then(|s| parse_lap_time_ms(Some(s)));
        let Some(best_lap_ms) = best_lap_ms else {
            continue;
        };
        valid_entries.push((
            entry,
            car,
            class_field.unwrap_or(""),
            best_lap_str.unwrap_or(""),
            best_lap_ms,
        ));
    }

    let corrected_grid: Vec<RawGridEntry> = valid_entries
        .iter()
        .map(|(_, car, class_field, _, _)| RawGridEntry {
            ca: car.clone(),
            cl: (*class_field).to_string(),
        })
        .collect();
    let race_class = detect_race_class(&corrected_grid);
    let mut lap_rows = 0usize;
    for (index, item) in valid_entries.iter().enumerate() {
        let (entry, car, _, best_lap_str, best_lap_ms) = item;
        let driver_raw = entry.get("dr").and_then(|v| v.as_str());
        let driver = sanitize_driver_name(driver_raw);
        let dirty = is_dirty_lap(Some(best_lap_str));
        let best_lap_clean = strip_dirty_symbol(best_lap_str);
        let raw_lap_json = serde_json::json!({
            "model_best_lap": best_lap_str,
        })
        .to_string();
        let temp_c =
            temp_f.and_then(|tf| forza_domain::lap::fahrenheit_to_celsius(tf, 40.0, 140.0));

        let id = format!("lap-{image_file_id}-{extraction_result_id}-{}", index + 1);
        conn.execute(
            "INSERT INTO lap_records
                (id, run_id, image_file_id, extraction_result_id, lap_index,
                 driver, driver_normalized, car, car_normalized,
                 race_class, track, track_normalized, weather, temp_f, temp_c,
                 best_lap, best_lap_ms, dirty, raw_lap_json, source_file, created_at)
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18,?19,?20,datetime('now'))",
            rusqlite::params![
                id,
                run_id,
                image_file_id,
                extraction_result_id,
                index as i64,
                &driver,
                driver.to_lowercase(),
                car,
                car.to_lowercase(),
                &race_class,
                &track_fixed,
                track_fixed.to_lowercase(),
                weather,
                temp_f,
                temp_c,
                best_lap_clean,
                best_lap_ms,
                dirty,
                raw_lap_json,
                source_file.unwrap_or(""),
            ],
        )
        .map_err(|e| e.to_string())?;
        lap_rows += 1;
    }
    Ok(lap_rows)
}
