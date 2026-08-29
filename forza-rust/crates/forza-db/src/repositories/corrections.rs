//! Manual review corrections: persisted operator decisions that survive
//! rebuild and are reapplied to lap rows before frontier recomputation.
//! Semantics mirror `forza/db/repositories/review_corrections.py`:
//! image-scoped fields (track/weather/race_class) apply to every lap of the
//! image; lap-scoped fields (dirty/car/driver) require a lap_index and apply
//! to that lap slot.

use rusqlite::{Connection, params};

use crate::error::DbError;
use forza_domain::lap::strip_dirty_symbol;

pub const CORRECTION_FIELDS: &[&str] =
    &["dirty", "track", "weather", "race_class", "car", "driver"];

const IMAGE_SCOPED: &[&str] = &["track", "weather", "race_class"];

/// Python `_bool_value`: dirty flag is true only for explicit truthy text.
fn bool_value(value: &str) -> bool {
    matches!(
        value.trim().to_lowercase().as_str(),
        "1" | "true" | "yes" | "y" | "on"
    )
}

/// One correction row read from `review_corrections`.
struct CorrectionRow {
    field: String,
    corrected_value: String,
    image_file_id: String,
    lap_index: Option<i64>,
}

fn load_corrections(conn: &Connection) -> Result<Vec<CorrectionRow>, DbError> {
    let mut stmt = conn.prepare(
        "SELECT field, corrected_value, image_file_id, lap_index
         FROM review_corrections ORDER BY created_at",
    )?;
    let rows = stmt.query_map([], |r| {
        Ok(CorrectionRow {
            field: r.get(0)?,
            corrected_value: r.get(1)?,
            image_file_id: r.get(2)?,
            lap_index: r.get(3)?,
        })
    })?;
    rows.collect::<Result<Vec<_>, _>>().map_err(DbError::from)
}

/// Mutate one lap row in place, mirroring `_apply_to_lap`.
fn apply_to_lap(
    conn: &Connection,
    lap_id: &str,
    correction: &CorrectionRow,
) -> Result<(), DbError> {
    let value = correction.corrected_value.as_str();
    match correction.field.as_str() {
        "dirty" => {
            let dirty = bool_value(value);
            conn.execute(
                "UPDATE lap_records SET dirty=?2 WHERE id=?1",
                params![lap_id, i64::from(dirty)],
            )?;
            if !dirty {
                // Un-dirtying also cleans the canonical lap time.
                let best_lap: String = conn.query_row(
                    "SELECT best_lap FROM lap_records WHERE id=?1",
                    params![lap_id],
                    |r| r.get(0),
                )?;
                let cleaned = strip_dirty_symbol(&best_lap);
                if cleaned != best_lap {
                    conn.execute(
                        "UPDATE lap_records SET best_lap=?2 WHERE id=?1",
                        params![lap_id, cleaned],
                    )?;
                }
            }
        }
        "track" => {
            conn.execute(
                "UPDATE lap_records SET track=?2, track_normalized=?3 WHERE id=?1",
                params![lap_id, value, value.to_lowercase()],
            )?;
        }
        "weather" => {
            conn.execute(
                "UPDATE lap_records SET weather=?2 WHERE id=?1",
                params![lap_id, value],
            )?;
        }
        "race_class" => {
            conn.execute(
                "UPDATE lap_records SET race_class=?2 WHERE id=?1",
                params![lap_id, value],
            )?;
        }
        "car" => {
            conn.execute(
                "UPDATE lap_records SET car=?2, car_normalized=?3 WHERE id=?1",
                params![lap_id, value, value.to_lowercase()],
            )?;
        }
        "driver" => {
            conn.execute(
                "UPDATE lap_records SET driver=?2, driver_normalized=?3 WHERE id=?1",
                params![lap_id, value, value.to_lowercase()],
            )?;
        }
        other => {
            let _ = other;
        }
    }
    Ok(())
}

/// Laps targeted by one correction: every lap of the image for image-scoped
/// fields; the matching lap slot for lap-scoped fields (0 laps when the
/// correction has no lap_index, like Python's `apply`).
fn laps_for_correction(
    conn: &Connection,
    correction: &CorrectionRow,
) -> Result<Vec<String>, DbError> {
    let mut lap_ids = Vec::new();
    if IMAGE_SCOPED.contains(&correction.field.as_str()) {
        let mut stmt = conn.prepare("SELECT id FROM lap_records WHERE image_file_id=?1")?;
        let rows = stmt.query_map(params![correction.image_file_id], |r| r.get::<_, String>(0))?;
        for id in rows {
            lap_ids.push(id?);
        }
    } else {
        let Some(lap_index) = correction.lap_index else {
            return Ok(lap_ids);
        };
        let mut stmt =
            conn.prepare("SELECT id FROM lap_records WHERE image_file_id=?1 AND lap_index=?2")?;
        let rows = stmt.query_map(params![correction.image_file_id, lap_index], |r| {
            r.get::<_, String>(0)
        })?;
        for id in rows {
            lap_ids.push(id?);
        }
    }
    Ok(lap_ids)
}

/// Apply every persisted correction with Python's scoping semantics; returns
/// the number of lap rows touched.
pub fn apply_all(conn: &Connection) -> Result<usize, DbError> {
    let corrections = load_corrections(conn)?;
    let mut applied = 0usize;
    for correction in &corrections {
        for lap_id in laps_for_correction(conn, correction)? {
            apply_to_lap(conn, &lap_id, correction)?;
            applied += 1;
        }
    }
    Ok(applied)
}

/// Resolve one review case as confirmed and record its correction (the
/// immediate GUI action). Applies to the case's linked lap plus every
/// scope-matched lap (image-scoped fields cover the whole image). Returns
/// the linked lap id when present, else the case business key.
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

    let (case_id, business_key, linked_lap): (String, String, Option<String>) = conn
        .query_row(
            "SELECT id, business_key, lap_record_id FROM review_cases WHERE case_number=?1",
            params![case_number],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .map_err(|e| DbError::SchemaState {
            message: format!("review case {case_number}: {e}"),
        })?;
    let _ = &case_id;

    // Persist the decision evidence (stable key keeps reapply deterministic).
    let stable_key = format!("{field}:{business_key}");
    conn.execute(
        "INSERT INTO review_corrections
            (id, stable_key, image_file_id, lap_index, field,
             model_value, corrected_value, cause, review_case_id,
             created_at, updated_at)
         SELECT ?1, ?2, c.image_file_id, c.lap_index, ?3,
                c.model_value, ?4, 'review', c.id, datetime('now'), datetime('now')
         FROM review_cases c WHERE c.case_number=?5
         ON CONFLICT(stable_key) DO UPDATE SET
             corrected_value=excluded.corrected_value, updated_at=excluded.updated_at",
        params![
            format!("corr-{case_number}-{field}"),
            stable_key,
            field,
            new_value,
            case_number
        ],
    )?;

    // Immediate effect with the same scoping `apply_all` will later repeat,
    // plus the case's own linked lap (which may fall outside the scope when
    // the correction carries no lap_index).
    let correction = CorrectionRow {
        field: field.to_string(),
        corrected_value: new_value.to_string(),
        image_file_id: conn
            .query_row(
                "SELECT COALESCE(image_file_id, '') FROM review_cases WHERE case_number=?1",
                params![case_number],
                |r| r.get(0),
            )
            .unwrap_or_default(),
        lap_index: conn
            .query_row(
                "SELECT lap_index FROM review_cases WHERE case_number=?1",
                params![case_number],
                |r| r.get(0),
            )
            .ok(),
    };
    let mut targets = laps_for_correction(conn, &correction)?;
    if let Some(linked) = &linked_lap
        && !targets.contains(linked)
    {
        targets.push(linked.clone());
    }
    for lap_id in &targets {
        apply_to_lap(conn, lap_id, &correction)?;
    }

    conn.execute(
        "UPDATE review_cases SET status='resolved', outcome='confirmed',
            decision_field=?2, corrected_value=?3, resolved_at=datetime('now'),
            updated_at=datetime('now')
         WHERE case_number=?1",
        params![case_number, field, new_value],
    )?;

    Ok(linked_lap.unwrap_or(business_key))
}
