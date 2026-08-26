//! Application-facing review queue operations.

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
    pub model_value: Option<String>,
    pub decision_field: Option<String>,
    pub lap_index: Option<i64>,
}

/// List review cases filtered by bucket (`open`, `resolved`, `all`).
/// `resolved` includes system-set `auto_resolved` (operator-equivalent).
/// `image_file_id` narrows the queue to one image (Image Detail tab).
pub fn list_review_cases(
    conn: &Connection,
    bucket: &str,
    image_file_id: Option<&str>,
) -> Result<Vec<ReviewCaseEntry>, String> {
    let status_filter = match bucket {
        "open" => "status = 'open'",
        "resolved" => "status IN ('resolved', 'auto_resolved')",
        _ => "1=1",
    };
    let image_filter = " AND (?1 IS NULL OR image_file_id = ?1)";
    let sql = format!(
        "SELECT case_number, reason, COALESCE(\"trigger\",''), status,
                COALESCE(outcome,''), COALESCE(driver,''), COALESCE(track,''),
                COALESCE(model_value,''), COALESCE(decision_field,''), lap_index
         FROM review_cases WHERE {status_filter}{image_filter}
         ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END, case_number"
    );
    let mut stmt = conn.prepare(&sql).map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map([image_file_id], |row| {
            Ok(ReviewCaseEntry {
                case_number: row.get(0)?,
                reason: row.get(1)?,
                trigger: Some(row.get(2)?),
                status: row.get(3)?,
                outcome: Some(row.get(4)?),
                driver: Some(row.get(5)?),
                track: Some(row.get(6)?),
                model_value: Some(row.get(7)?),
                decision_field: Some(row.get(8)?),
                lap_index: row.get(9)?,
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
