//! Response cleaning, strict parse+validation, and semantic retry issues.
//! Ported from `forza/pipeline/model_response.py` and the backend's
//! `_semantic_retry_issues`.

use serde_json::Value;

use forza_domain::lap::{parse_lap_time_ms, strip_dirty_symbol};

/// Strip markdown fences and surrounding whitespace from model JSON.
pub fn clean_json_content(text: &str) -> String {
    let trimmed = text.trim();
    let mut out = trimmed.to_string();
    if out.len() >= 3 {
        // ^```(?:json)?\s*
        if let Some(rest) = out.strip_prefix("```") {
            let rest = rest.strip_prefix("json").unwrap_or(rest);
            out = rest.trim_start().to_string();
        }
    }
    // \s*```$
    while out.ends_with("```") {
        out.truncate(out.len() - 3);
        out = out.trim_end().to_string();
    }
    out.trim().to_string()
}

fn extract_object(text: &str) -> Option<&str> {
    let start = text.find('{')?;
    let end = text.rfind('}')?;
    if end < start {
        return None;
    }
    Some(&text[start..=end])
}

/// Strict parse + validation of the short-key extraction JSON.
///
/// Repair path (fence stripping plus brace-windowing) is intentionally
/// minimal: real malformed fixtures fail on validation, not syntax.
pub fn parse_and_validate_response(content: &str) -> Result<Value, String> {
    let cleaned = clean_json_content(content);
    let first_err = match serde_json::from_str::<Value>(&cleaned) {
        Ok(value) => {
            if !value.is_object() {
                return Err("Response is not a JSON object".into());
            }
            return validate_extracted_response(&value).map(|_| value);
        }
        Err(err) => err.to_string(),
    };

    // Fallback window: some models wrap the object in stray prose.
    if let Some(windowed) = extract_object(&cleaned)
        && windowed != cleaned.as_str()
        && let Ok(value) = serde_json::from_str::<Value>(windowed)
    {
        if !value.is_object() {
            return Err("Response is not a JSON object".into());
        }
        return validate_extracted_response(&value).map(|_| value);
    }
    Err(first_err)
}

/// Validation mirroring `validate_extracted_response`.
pub fn validate_extracted_response(data: &Value) -> Result<(), String> {
    let obj = data
        .as_object()
        .ok_or_else(|| "Response is not a JSON object".to_string())?;
    if !obj.contains_key("t") {
        return Err("Missing field 't' (track name)".into());
    }
    let entries = data
        .get("e")
        .ok_or_else(|| "Missing or invalid field 'e' (entries list)".to_string())?;
    let entries = entries
        .as_array()
        .ok_or_else(|| "Missing or invalid field 'e' (entries list)".to_string())?;
    for (index, entry) in entries.iter().enumerate() {
        let entry = entry
            .as_object()
            .ok_or_else(|| format!("Entry {index} missing field 'dr'"))?;
        for field in ["dr", "ca", "cl", "bl"] {
            if !entry.contains_key(field) {
                return Err(format!("Entry {index} missing field '{field}'"));
            }
        }
        if let Some(bl) = entry.get("bl")
            && !bl.is_null()
        {
            let bl_str = strip_dirty_symbol(bl.to_string().trim_matches('"'));
            if parse_lap_time_ms(Some(&bl_str)).is_none() {
                return Err(format!(
                    "Entry {index} has unparseable lap time: '{}'",
                    bl_str
                ));
            }
        }
    }
    Ok(())
}

/// Issues worth a model retry without treating partial lists as bad.
pub fn semantic_retry_issues(parsed: &Value) -> Vec<String> {
    let mut issues = Vec::new();
    let track = parsed.get("t").and_then(|v| v.as_str()).unwrap_or("");
    if track.trim().is_empty() {
        issues.push("track_empty".into());
    }
    let entries = parsed.get("e").and_then(|v| v.as_array());
    let Some(entries) = entries else {
        issues.push("entries_empty".into());
        return issues;
    };
    if entries.is_empty() {
        issues.push("entries_empty".into());
        return issues;
    }
    let lap_values: Vec<Option<&Value>> = entries
        .iter()
        .filter_map(|e| e.get("bl"))
        .map(Some)
        .collect();
    // Mirror the validator's extraction (`to_string` + quote-trim): using
    // `as_str` here counted numeric lap times as null and forced a wasted
    // semantic retry for payloads the validator itself accepts.
    if !lap_values.is_empty()
        && lap_values.iter().all(|bl| {
            bl.map(|v| strip_dirty_symbol(v.to_string().trim_matches('"')))
                .and_then(|s| parse_lap_time_ms(Some(&s)))
                .is_none()
        })
    {
        issues.push("all_best_laps_null".into());
    }
    issues
}
