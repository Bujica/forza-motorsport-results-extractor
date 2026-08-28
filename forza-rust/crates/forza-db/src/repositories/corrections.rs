//! Manual review corrections: persisted operator decisions that survive
//! rebuild and are reapplied to lap rows before frontier recomputation.

use rusqlite::{Connection, params};

use crate::error::DbError;

pub const CORRECTION_FIELDS: &[&str] =
    &["dirty", "track", "weather", "race_class", "car", "driver"];

/// Apply one manual correction to the lap behind a review case and resolve
/// it as confirmed. Returns the affected lap id.
pub fn apply_manual_correction(
    conn: &Connection,
    case_number: i64,
    field: &str,
    new_value: &str,
    _gamertag: Option<&str>,
) -> Result<String, DbError> {
    if !CORRECTION_FIELDS.contains(&field) {
        return Err(DbError::SchemaState {
            message: format!("invalid correction field '{field}'"),
        });
    }

    let (case_id, business_key, lap_id): (String, String, Option<String>) = conn
        .query_row(
            "SELECT id, business_key, lap_record_id FROM review_cases WHERE case_number=?1",
            params![case_number],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .map_err(|e| DbError::SchemaState {
            message: format!("review case {case_number}: {e}"),
        })?;

    let Some(lap_id) = lap_id else {
        return Err(DbError::SchemaState {
            message: format!("review case {case_number} has no linked lap"),
        });
    };

    // Field-specific typed updates (dirty is boolean; others text).
    match field {
        "dirty" => {
            let flag = matches!(new_value.to_lowercase().as_str(), "false" | "0" | "no");
            conn.execute(
                "UPDATE lap_records SET dirty=?2 WHERE id=?1",
                params![lap_id, if flag { 0 } else { 1 }],
            )?;
        }
        _ => {
            let normalized = match field {
                "track" => {
                    let refs = forza_domain::reference_data::embedded_reference_data();
                    forza_domain::normalizer::fix_track_name(new_value, &refs)
                        .unwrap_or_else(|| new_value.to_string())
                }
                "car" => {
                    let refs = forza_domain::reference_data::embedded_reference_data();
                    forza_domain::normalizer::fix_car_name(new_value, &refs)
                }
                _ => new_value.to_string(),
            };
            let sql = format!(
                "UPDATE lap_records SET {field}=?2, {field}_normalized=LOWER(?2) WHERE id=?1"
            );
            conn.execute(&sql, params![lap_id, normalized])?;
        }
    }

    // Persist the decision evidence (stable key keeps reapply deterministic).
    let stable_key = format!("{field}:{business_key}:{lap_id}");
    let cause = "review";
    // model_value already lives on the review case row; no need to copy here.
    let lap_index: Option<i64> = conn
        .query_row(
            "SELECT lap_index FROM review_cases WHERE case_number=?1",
            params![case_number],
            |r| r.get(0),
        )
        .ok();
    conn.execute(
        "INSERT INTO review_corrections
            (id, stable_key, image_file_id, lap_index, field,
             model_value, corrected_value, cause, review_case_id,
             created_at, updated_at)
         SELECT ?1, ?2, c.image_file_id, c.lap_index, ?3,
                c.model_value, ?4, ?5, c.id, datetime('now'), datetime('now')
         FROM review_cases c WHERE c.case_number=?6
         ON CONFLICT(stable_key) DO UPDATE SET
             corrected_value=excluded.corrected_value, updated_at=excluded.updated_at",
        params![
            format!("corr-{case_number}-{field}"),
            stable_key,
            field,
            new_value,
            cause,
            case_number
        ],
    )?;
    let _ = lap_index;

    conn.execute(
        "UPDATE review_cases SET status='resolved', outcome='confirmed',
            decision_field=?2, corrected_value=?3, resolved_at=datetime('now'),
            updated_at=datetime('now')
         WHERE case_number=?1",
        params![case_number, field, new_value],
    )?;
    let _ = case_id;

    Ok(lap_id)
}

/// Apply every persisted correction to its matching lap_record, then clear
/// dirty markers on best-lap rows whose dirty flag was just reset.
/// Returns the number of corrections applied.
pub fn apply_all(conn: &Connection) -> Result<usize, DbError> {
    let mut stmt = conn.prepare(
        "SELECT rc.field, rc.corrected_value, r.lap_record_id
         FROM review_corrections rc
         JOIN review_cases r ON r.id = rc.review_case_id
         ORDER BY rc.created_at",
    )?;

    let rows: Vec<(String, String, Option<String>)> = stmt
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))
        .map_err(DbError::from)?
        .filter_map(|row| row.ok())
        .collect();

    let mut applied = 0usize;

    for (field, corrected_value, lap_id_opt) in rows {
        let Some(lap_id) = lap_id_opt else {
            continue;
        };
        match field.as_str() {
            "dirty" => {
                let flag = matches!(
                    corrected_value.to_lowercase().as_str(),
                    "false" | "0" | "no"
                );
                conn.execute(
                    "UPDATE lap_records SET dirty=?2 WHERE id=?1",
                    params![lap_id, if flag { 0 } else { 1 }],
                )?;
            }
            "track" => {
                let refs = forza_domain::reference_data::embedded_reference_data();
                let normalized = forza_domain::normalizer::fix_track_name(&corrected_value, &refs)
                    .unwrap_or_else(|| corrected_value.clone());
                let sql = "UPDATE lap_records SET track=?2, track_normalized=LOWER(?2) WHERE id=?1";
                conn.execute(sql, params![lap_id, normalized])?;
            }
            "weather" => {
                let sql =
                    "UPDATE lap_records SET weather=?2, weather_normalized=LOWER(?2) WHERE id=?1";
                conn.execute(sql, params![lap_id, corrected_value])?;
            }
            "race_class" => {
                let sql = "UPDATE lap_records SET race_class=?2, race_class_normalized=LOWER(?2) WHERE id=?1";
                conn.execute(sql, params![lap_id, corrected_value])?;
            }
            "car" => {
                let refs = forza_domain::reference_data::embedded_reference_data();
                let normalized = forza_domain::normalizer::fix_car_name(&corrected_value, &refs);
                let sql = "UPDATE lap_records SET car=?2, car_normalized=LOWER(?2) WHERE id=?1";
                conn.execute(sql, params![lap_id, normalized])?;
            }
            "driver" => {
                let sql =
                    "UPDATE lap_records SET driver=?2, driver_normalized=LOWER(?2) WHERE id=?1";
                conn.execute(sql, params![lap_id, corrected_value])?;
            }
            _ => continue,
        }
        applied += 1;
    }

    Ok(applied)
}
