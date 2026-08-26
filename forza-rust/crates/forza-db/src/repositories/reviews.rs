//! Review candidate detection, business-key identity, and case upsert that
//! preserves operator decisions. Ports `review_identity.py`, the candidate
//! rules in `laps.py::_append_row_review_candidates`, and
//! `ReviewRepository.upsert_review_cases`.

use std::collections::HashSet;

use rusqlite::{Connection, params};

use forza_domain::reference_data::embedded_reference_data;
use forza_domain::review_rules::driver_name_review_trigger;

/// Review reason vocabulary (persisted values).
pub const LAP_SCOPED: &[&str] = &["dirty_lap", "car", "driver_name"];
pub const IMAGE_SCOPED: &[&str] = &["track", "weather", "race_class"];

#[derive(Debug, Clone, PartialEq)]
pub struct ReviewCaseInsert<'a> {
    pub business_key: &'a str,
    pub case_number: i64,
    pub reason: &'a str,
    pub trigger_name: Option<&'a str>,
    pub status: &'a str,
    pub outcome: &'a str,
    pub image_file_id: Option<&'a str>,
}

pub fn insert_review_case(
    conn: &Connection,
    row: &ReviewCaseInsert<'_>,
) -> Result<(), crate::DbError> {
    let id = format!("case-{}", row.case_number);
    conn.execute(
        "INSERT INTO review_cases
            (id, business_key, case_number, reason, \"trigger\", status, outcome, image_file_id, created_at)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, datetime('now'))",
        params![
            id,
            row.business_key,
            row.case_number,
            row.reason,
            row.trigger_name,
            row.status,
            row.outcome,
            row.image_file_id,
        ],
    )?;
    Ok(())
}

#[derive(Debug, Clone, PartialEq)]
pub struct LapCandidateRow {
    pub lap_id: String,
    pub image_file_id: String,
    pub lap_index: i64,
    pub driver: String,
    pub source_file: Option<String>,
    pub best_lap: Option<String>,
    pub track: String,
    pub weather: String,
    pub race_class: String,
    pub car: String,
    pub dirty: bool,
    pub is_best_lap: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ReviewCandidate {
    pub reason: &'static str,
    pub trigger: &'static str,
    pub model_value: String,
    /// Image-scoped cases collapse to one row per image.
    pub per_image: bool,
    pub row: LapCandidateRow,
}

pub fn canonical_business_key(candidate: &ReviewCandidate) -> String {
    let reason = candidate.reason;
    let image = &candidate.row.image_file_id;
    let lap_index = &candidate.row.lap_index;
    let driver_norm = candidate.row.driver.trim().to_lowercase();
    if LAP_SCOPED.contains(&reason) && !image.is_empty() {
        format!("{reason}:{image}:{lap_index}")
    } else if IMAGE_SCOPED.contains(&reason) && !image.is_empty() {
        format!("{reason}:{image}")
    } else if !image.is_empty() || !driver_norm.is_empty() {
        format!("{reason}:{image}:{lap_index}:{driver_norm}")
    } else {
        let source = candidate.row.source_file.clone().unwrap_or_default();
        let best = candidate.row.best_lap.clone().unwrap_or_default();
        format!("{reason}:fallback:{source}:{driver_norm}:{best}")
    }
}

fn known_track_keys() -> HashSet<String> {
    embedded_reference_data()
        .tracks
        .iter()
        .map(|t| t.to_lowercase())
        .collect()
}

fn known_cars() -> HashSet<String> {
    embedded_reference_data()
        .cars
        .iter()
        .map(|c| c.trim().to_lowercase())
        .collect()
}

const VALID_CLASSES: &[&str] = &["E", "D", "C", "B", "A", "TCR", "S", "R", "P", "X"];

/// Detect review candidates from persisted lap rows (global, not run-scoped).
pub fn query_review_candidates(conn: &Connection) -> Result<Vec<ReviewCandidate>, crate::DbError> {
    let mut stmt = conn.prepare(
        "SELECT id, image_file_id, lap_index, driver, source_file, best_lap,
                track, COALESCE(weather,'unknown'), race_class, car, dirty, is_best_lap
         FROM lap_records ORDER BY id",
    )?;
    let rows = stmt.query_map([], |row| {
        Ok(LapCandidateRow {
            lap_id: row.get(0)?,
            image_file_id: row.get(1)?,
            lap_index: row.get(2)?,
            driver: row.get(3)?,
            source_file: row.get(4)?,
            best_lap: row.get(5)?,
            track: row.get(6)?,
            weather: row.get(7)?,
            race_class: row.get(8)?,
            car: row.get(9)?,
            dirty: row.get::<_, i64>(10)? != 0,
            is_best_lap: row.get::<_, i64>(11)? != 0,
        })
    })?;
    let laps: Vec<LapCandidateRow> = rows.collect::<Result<_, _>>()?;

    let tracks = known_track_keys();
    let cars = known_cars();
    let mut candidates: Vec<ReviewCandidate> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    let mut push = |reason: &'static str,
                    trigger: &'static str,
                    model_value: String,
                    per_image: bool,
                    row: &LapCandidateRow| {
        let probe = ReviewCandidate {
            reason,
            trigger,
            model_value,
            per_image,
            row: row.clone(),
        };
        let key = canonical_business_key(&probe);
        if seen.insert(key) {
            candidates.push(probe);
        }
    };

    for row in &laps {
        // Dirty-lap review only when it impacts Best Laps output.
        if row.dirty && row.is_best_lap {
            push("dirty_lap", "model_marked_dirty", "true".into(), false, row);
        }
        if row.weather.eq_ignore_ascii_case("unknown") {
            push("weather", "weather_unknown", row.weather.clone(), true, row);
        }
        if row.track.is_empty() || row.track == "Unknown" {
            push("track", "track_unknown", row.track.clone(), true, row);
        }
        if row.track.to_lowercase().contains("ambiguous") {
            push("track", "track_unresolved", row.track.clone(), true, row);
        }
        if !row.track.is_empty() && !tracks.contains(&row.track.to_lowercase()) {
            push(
                "track",
                "track_not_in_reference",
                row.track.clone(),
                true,
                row,
            );
        }
        if row.race_class == "Unknown" {
            push(
                "race_class",
                "class_unknown",
                row.race_class.clone(),
                true,
                row,
            );
        } else if !VALID_CLASSES.contains(&row.race_class.as_str()) {
            push(
                "race_class",
                "class_invalid",
                row.race_class.clone(),
                true,
                row,
            );
        }
        if let Some(trigger) = driver_name_review_trigger(Some(&row.driver)) {
            push(
                "driver_name",
                match trigger {
                    "numeric_prefix" => "numeric_prefix",
                    "invalid_symbol" => "invalid_symbol",
                    _ => "driver_name_empty",
                },
                row.driver.clone(),
                false,
                row,
            );
        }
        if row.car.trim().is_empty() {
            push("car", "car_empty", row.car.clone(), false, row);
        } else if !cars.contains(&row.car.trim().to_lowercase()) {
            push("car", "car_not_in_reference", row.car.clone(), false, row);
        }
    }

    // Rain-time suspicious check (rain best faster than dry best per group)
    // lands with the full review parity pass in Fase 8½.

    Ok(candidates)
}

/// Upsert candidates preserving user-owned terminal states. Returns
/// (inserted, kept, auto_resolved).
pub fn upsert_review_cases(
    conn: &Connection,
    candidates: &[ReviewCandidate],
) -> Result<(usize, usize, usize), crate::DbError> {
    let mut inserted = 0;
    let mut kept = 0;

    let incoming_keys: HashSet<String> = candidates.iter().map(canonical_business_key).collect();

    // Auto-resolve open cases whose condition disappeared.
    let existing_open: Vec<String> = {
        let mut stmt =
            conn.prepare("SELECT business_key FROM review_cases WHERE status IN ('open')")?;
        let rows = stmt.query_map([], |r| r.get::<_, String>(0))?;
        rows.collect::<Result<_, _>>()?
    };
    let mut auto_resolved = 0;
    for key in existing_open {
        if !incoming_keys.contains(key.as_str()) {
            conn.execute(
                "UPDATE review_cases SET status='auto_resolved', updated_at=datetime('now')
                 WHERE business_key=?1 AND status='open'",
                params![key],
            )?;
            auto_resolved += 1;
        }
    }

    for candidate in candidates {
        let key = canonical_business_key(candidate);
        let exists: bool = conn
            .query_row(
                "SELECT COUNT(*) FROM review_cases WHERE business_key=?1 AND status IN ('open','resolved','ignored','auto_resolved')",
                params![key],
                |r| r.get::<_, i64>(0),
            )
            .map(|n| n > 0)?;
        if exists {
            kept += 1;
            continue;
        }
        let next_number: i64 = conn.query_row(
            "SELECT COALESCE(MAX(case_number),0)+1 FROM review_cases",
            [],
            |r| r.get(0),
        )?;
        let id = format!("case-{}", next_number);
        conn.execute(
            "INSERT INTO review_cases
                (id, reason, business_key, \"trigger\", status, outcome,
                 image_file_id, lap_record_id, lap_index, driver, driver_normalized,
                 track, model_value, case_number, created_at, updated_at)
             VALUES (?1,?2,?3,?4,'open','pending',?5,?6,?7,?8,LOWER(?8),?9,?10,?11,datetime('now'),datetime('now'))",
            params![
                id,
                candidate.reason,
                key,
                candidate.trigger,
                candidate.row.image_file_id,
                candidate.row.lap_id,
                if candidate.per_image { None } else { Some(candidate.row.lap_index) },
                candidate.row.driver,
                candidate.row.track,
                candidate.model_value,
                next_number,
            ],
        )?;
        inserted += 1;
    }

    Ok((inserted, kept, auto_resolved))
}
