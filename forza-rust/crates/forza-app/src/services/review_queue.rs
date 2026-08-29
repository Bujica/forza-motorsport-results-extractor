//! Application-facing review queue operations.
//!
//! Listing mirrors the Python `list_review_queue` read model: bucket +
//! status/reason/outcome/run filters, and the full row set the operator UI
//! needs (decision, correction, error, session context).

use rusqlite::Connection;

use forza_db::repositories::corrections::apply_manual_correction;

#[derive(Debug, Clone, PartialEq)]
pub struct ReviewCaseEntry {
    pub case_number: i64,
    pub reason: String,
    pub trigger: Option<String>,
    pub status: String,
    pub outcome: Option<String>,
    pub driver: Option<String>,
    pub track: Option<String>,
    pub race_class: Option<String>,
    pub weather: Option<String>,
    pub best_lap: Option<String>,
    pub temp_f: Option<f64>,
    pub model_value: Option<String>,
    pub corrected_value: Option<String>,
    pub decision_field: Option<String>,
    pub error_type: Option<String>,
    pub lap_index: Option<i64>,
    pub image_file_id: Option<String>,
    pub run_id: Option<String>,
    pub source_file: Option<String>,
}

/// Filters for the review listing; `None`/empty/"all" values pass through.
#[derive(Debug, Clone, Default)]
pub struct ReviewQueueFilter {
    pub bucket: String,
    pub reason: Option<String>,
    pub outcome: Option<String>,
    pub run_id: Option<String>,
    pub image_file_id: Option<String>,
}

/// List review cases. `resolved` includes system-set `auto_resolved`
/// (operator-equivalent). Open cases sort first, then by case number.
pub fn list_review_cases(
    conn: &Connection,
    filter: &ReviewQueueFilter,
) -> Result<Vec<ReviewCaseEntry>, String> {
    let bucket = filter.bucket.as_str();
    let status_filter = match bucket {
        "open" => "status = 'open'",
        "resolved" => "status IN ('resolved', 'auto_resolved')",
        _ => "1=1",
    };

    let mut clauses: Vec<String> = vec![status_filter.to_string()];
    let mut args: Vec<Box<dyn rusqlite::types::ToSql>> = Vec::new();
    if let Some(reason) = filter
        .reason
        .as_deref()
        .filter(|v| !v.is_empty() && *v != "all")
    {
        clauses.push("reason = ?".to_string());
        args.push(Box::new(reason.to_string()));
    }
    if let Some(outcome) = filter
        .outcome
        .as_deref()
        .filter(|v| !v.is_empty() && *v != "all")
    {
        clauses.push("outcome = ?".to_string());
        args.push(Box::new(outcome.to_string()));
    }
    if let Some(run) = filter
        .run_id
        .as_deref()
        .filter(|v| !v.is_empty() && *v != "all")
    {
        clauses.push("run_id = ?".to_string());
        args.push(Box::new(run.to_string()));
    }
    if let Some(image) = filter.image_file_id.as_deref().filter(|v| !v.is_empty()) {
        clauses.push("image_file_id = ?".to_string());
        args.push(Box::new(image.to_string()));
    }

    let sql = format!(
        "SELECT case_number, reason, COALESCE(\"trigger\",''), status,
                COALESCE(outcome,''), COALESCE(driver,''), COALESCE(track,''),
                COALESCE(race_class,''), COALESCE(weather,''), COALESCE(best_lap,''),
                temp_f, COALESCE(model_value,''), corrected_value,
                COALESCE(decision_field,''), COALESCE(error_type,''), lap_index,
                image_file_id, run_id, COALESCE(source_file,'')
         FROM review_cases
         WHERE {}
         ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END, case_number",
        clauses.join(" AND ")
    );
    let params_ref: Vec<&dyn rusqlite::types::ToSql> =
        args.iter().map(|item| item.as_ref()).collect();
    let mut stmt = conn.prepare(&sql).map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map(params_ref.as_slice(), |row| {
            Ok(ReviewCaseEntry {
                case_number: row.get(0)?,
                reason: row.get(1)?,
                trigger: Some(row.get(2)?),
                status: row.get(3)?,
                outcome: Some(row.get(4)?),
                driver: Some(row.get(5)?),
                track: Some(row.get(6)?),
                race_class: Some(row.get(7)?),
                weather: Some(row.get(8)?),
                best_lap: Some(row.get(9)?),
                temp_f: row.get(10)?,
                model_value: Some(row.get(11)?),
                corrected_value: row.get(12)?,
                decision_field: Some(row.get(13)?),
                error_type: Some(row.get(14)?),
                lap_index: row.get(15)?,
                image_file_id: row.get(16)?,
                run_id: row.get(17)?,
                source_file: Some(row.get(18)?),
            })
        })
        .map_err(|e| e.to_string())?;
    rows.collect::<Result<_, _>>().map_err(|e| e.to_string())
}

/// Apply an operator decision to a case. `value` semantics depend on field
/// (`dirty`: true/false; others: corrected text).
pub fn decide_case(
    conn: &mut Connection,
    case_number: i64,
    field: &str,
    value: &str,
) -> Result<(), String> {
    apply_manual_correction(conn, case_number, field, value, None)
        .map(|_| ())
        .map_err(|e| e.to_string())
}

/// Ignore a case without touching data (operator says it is not actionable).
pub fn ignore_case(conn: &Connection, case_number: i64) -> Result<(), String> {
    conn.execute(
        "UPDATE review_cases SET status='ignored', outcome='ignored',
            resolved_at=datetime('now'), updated_at=datetime('now')
         WHERE case_number=?1 AND status='open'",
        rusqlite::params![case_number],
    )
    .map_err(|e| e.to_string())?;
    Ok(())
}

/// Reopen a resolved/ignored case back to open (Python reopen_review_case).
pub fn reopen_case(conn: &Connection, case_number: i64) -> Result<(), String> {
    let changed = conn
        .execute(
            "UPDATE review_cases SET status='open', outcome='pending',
                resolved_at=NULL, updated_at=datetime('now')
             WHERE case_number=?1 AND status <> 'open'",
            rusqlite::params![case_number],
        )
        .map_err(|e| e.to_string())?;
    if changed == 0 {
        return Err(format!("case {case_number} is not resolved"));
    }
    Ok(())
}
