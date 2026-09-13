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
    pub car: Option<String>,
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
    pub resolution_note: Option<String>,
    /// Linked lap row id (resolution order: this, then image+index, then
    /// first lap of the image — Python `_current_review_lap` parity).
    pub lap_record_id: Option<String>,
    /// Live lap time/dirtness resolved per case (Python `current_best_lap` /
    /// `current_dirty` parity). The stored `best_lap` column is never
    /// written by upsert, so the Lap column would stay empty without this.
    pub current_best_lap: Option<String>,
    pub current_lap_dirty: Option<bool>,
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
        // The stored outcome vocabulary has no system-resolved value
        // (CHECK-enforced): `auto_resolved` rows keep `outcome='pending'`,
        // so both labels map back to the lifecycle status here. Without
        // this, `pending` would also match system-closed rows.
        if outcome == "auto_resolved" {
            clauses.push("status = 'auto_resolved'".to_string());
        } else if outcome == "pending" {
            clauses.push("status = 'open'".to_string());
        } else {
            clauses.push("outcome = ?".to_string());
            args.push(Box::new(outcome.to_string()));
        }
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
                COALESCE(outcome,''), COALESCE(driver,''), COALESCE(car,''), COALESCE(track,''),
                COALESCE(race_class,''), COALESCE(weather,''), COALESCE(best_lap,''),
                temp_f, COALESCE(model_value,''), corrected_value,
                COALESCE(decision_field,''), COALESCE(error_type,''), lap_index,
                image_file_id, run_id, COALESCE(source_file,''), COALESCE(resolution_note,''),
                lap_record_id
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
                car: Some(row.get(6)?),
                track: Some(row.get(7)?),
                race_class: Some(row.get(8)?),
                weather: Some(row.get(9)?),
                best_lap: Some(row.get(10)?),
                temp_f: row.get(11)?,
                model_value: Some(row.get(12)?),
                corrected_value: row.get(13)?,
                decision_field: Some(row.get(14)?),
                error_type: Some(row.get(15)?),
                lap_index: row.get(16)?,
                image_file_id: row.get(17)?,
                run_id: row.get(18)?,
                source_file: Some(row.get(19)?),
                resolution_note: Some(row.get(20)?),
                lap_record_id: row.get(21)?,
                current_best_lap: None,
                current_lap_dirty: None,
            })
        })
        .map_err(|e| e.to_string())?;
    let mut rows = rows
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| e.to_string())?;
    // Resolve the live lap per case (Python `_current_review_lap` parity):
    // linked row, else image+index, else first lap of the image.
    for entry in &mut rows {
        let current: Option<(String, bool)> = entry
            .lap_record_id
            .as_deref()
            .and_then(|id| lap_best_where(conn, "id = ?1", [id]))
            .or_else(|| match (&entry.image_file_id, entry.lap_index) {
                (Some(image), Some(index)) => lap_best_where(
                    conn,
                    "image_file_id = ?1 AND lap_index = ?2",
                    rusqlite::params![image, index],
                ),
                _ => None,
            })
            .or_else(|| {
                entry.image_file_id.as_deref().and_then(|image| {
                    lap_best_where(
                        conn,
                        "image_file_id = ?1 ORDER BY lap_index LIMIT 1",
                        [image],
                    )
                })
            });
        if let Some((best_lap, dirty)) = current {
            entry.current_best_lap = Some(best_lap);
            entry.current_lap_dirty = Some(dirty);
        }
    }
    Ok(rows)
}

/// Best lap + dirty flag of the first lap row matching a predicate.
fn lap_best_where(
    conn: &Connection,
    predicate: &str,
    params: impl rusqlite::Params,
) -> Option<(String, bool)> {
    conn.query_row(
        &format!("SELECT best_lap, dirty FROM lap_records WHERE {predicate}"),
        params,
        |row| {
            let best_lap: String = row.get(0)?;
            let dirty: i64 = row.get(1)?;
            Ok((best_lap, dirty != 0))
        },
    )
    .ok()
}

/// Apply an operator decision to a case. `value` semantics depend on field
/// (`dirty`: true/false; others: corrected text).
///
/// A confirmed `car` correction also seeds the reference catalog: once the
/// operator confirms a novel car exists, later images match it without a new
/// review case (`INSERT OR IGNORE`, so re-confirming is a no-op).
pub fn decide_case(
    conn: &mut Connection,
    case_number: i64,
    field: &str,
    value: &str,
) -> Result<(), String> {
    apply_manual_correction(conn, case_number, field, value, None)
        .map(|_| ())
        .map_err(|e| e.to_string())?;
    if field == "car" && !value.trim().is_empty() {
        let inserted = forza_db::repositories::external_records::seed_reference_cars(
            conn,
            std::iter::once(value),
        )
        .map_err(|e| e.to_string())?;
        // A genuinely novel confirmation also joins the shipped assets so a
        // regenerated database does not redetect it. Best-effort: the DB
        // catalog already holds it, so asset failures never fail the decision.
        if inserted > 0 {
            let _ = super::reference_assets::sync_confirmed_car(value);
        }
    }
    Ok(())
}

/// Reopen a resolved case back to open (Python reopen_review_case).
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
