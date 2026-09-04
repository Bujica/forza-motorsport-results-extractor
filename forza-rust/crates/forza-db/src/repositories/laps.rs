//! `lap_records` repository: insert path, queries, and review candidate detection.

use std::collections::HashMap;

use crate::error::DbError;
use forza_domain::lap::strip_dirty_symbol;
use rusqlite::{Connection, params};

/// Clean-flat export row for output artifacts (CSV/PDF).
#[derive(Debug, Clone, PartialEq)]
pub struct ExportFlatRow {
    pub track: String,
    pub race_class: String,
    pub weather: Option<String>,
    pub temp_f: Option<f64>,
    pub temp_c: Option<f64>,
    pub driver: String,
    pub car: String,
    pub best_lap: Option<String>,
    pub best_lap_ms: Option<i64>,
    pub dirty: bool,
    pub source_file: Option<String>,
    /// Origin image id (`image_files.id`), when the lap came from a screenshot.
    pub image_file_id: Option<String>,
    /// ISO date portion of the image file modification timestamp.
    pub race_date: Option<String>,
    pub image_format: Option<String>,
    pub width_px: Option<i64>,
    pub height_px: Option<i64>,
    pub mine: bool,
}

/// Best-lap rows joined with their image metadata for output artifacts.
pub fn list_clean_flat(
    conn: &Connection,
    gamertag_lower: &str,
) -> Result<Vec<ExportFlatRow>, DbError> {
    let mut stmt = conn.prepare(
        "SELECT l.track, l.race_class, COALESCE(l.weather,'unknown'),
                l.temp_f, l.temp_c, l.driver, l.car, l.best_lap, l.best_lap_ms, l.dirty,
                l.source_file, l.image_file_id, i.race_date, i.image_format, i.width_px, i.height_px
         FROM lap_records l
         LEFT JOIN image_files i ON i.id = l.image_file_id
         WHERE l.is_best_lap = 1
         ORDER BY LOWER(l.track), LOWER(l.race_class), LOWER(l.driver), l.best_lap_ms",
    )?;
    let rows = stmt.query_map([], |row| {
        let modified: Option<String> = row.get(12)?;
        Ok(ExportFlatRow {
            track: row.get(0)?,
            race_class: row.get(1)?,
            weather: row.get(2)?,
            temp_f: row.get(3)?,
            temp_c: row.get(4)?,
            driver: row.get(5)?,
            car: row.get(6)?,
            best_lap: row.get(7)?,
            best_lap_ms: row.get(8)?,
            dirty: row.get::<_, i64>(9)? != 0,
            source_file: row.get(10)?,
            image_file_id: row.get(11)?,
            race_date: modified
                .as_ref()
                .map(|m| m.get(..10).unwrap_or(m).to_string()),
            image_format: row.get(13)?,
            width_px: row.get(14)?,
            height_px: row.get(15)?,
            mine: false,
        })
    })?;
    let mut out: Vec<_> = rows.collect::<Result<_, _>>()?;
    for row in &mut out {
        row.mine = row.driver.to_lowercase() == gamertag_lower;
    }
    Ok(out)
}

#[allow(clippy::struct_excessive_bools)]
pub struct LapRecordInsert<'a> {
    pub run_id: &'a str,
    pub image_file_id: &'a str,
    pub extraction_result_id: &'a str,
    pub attempt_id: Option<&'a str>,
    pub lap_index: i64,
    pub driver: &'a str,
    pub car: &'a str,
    pub race_class: &'a str,
    pub track: &'a str,
    pub weather: &'a str,
    pub temp_f: f64,
    pub best_lap: &'a str,
    pub best_lap_ms: i64,
    pub dirty: bool,
}

pub fn insert_lap_record(conn: &Connection, row: &LapRecordInsert<'_>) -> Result<(), DbError> {
    let id = format!("lap-{}-{}", row.image_file_id, row.lap_index);
    conn.execute(
        "INSERT INTO lap_records
            (id, run_id, image_file_id, extraction_result_id, lap_index,
             driver, driver_normalized, car, car_normalized,
             race_class, track, track_normalized, weather, temp_f, temp_c,
             best_lap, best_lap_ms, dirty, created_at)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?6, ?7, ?7, ?8, ?9, ?9, ?10, ?11,
                 ROUND((?11 - 32.0) * 5.0 / 9.0, 1), ?12, ?13, ?14, datetime('now'))",
        params![
            id,
            row.run_id,
            row.image_file_id,
            row.extraction_result_id,
            row.lap_index,
            row.driver,
            row.car,
            row.race_class,
            row.track,
            row.weather,
            row.temp_f,
            row.best_lap,
            row.best_lap_ms,
            row.dirty,
        ],
    )?;
    Ok(())
}

#[derive(Debug, Clone, PartialEq)]
pub struct LapRecordEntity {
    pub id: String,
    pub extraction_result_id: Option<String>,
    pub image_file_id: String,
    pub lap_index: i32,
    pub driver: String,
    pub car: String,
    pub race_class: String,
    pub track: String,
    pub weather: String,
    pub temp_f: f64,
    pub best_lap: String,
    pub best_lap_ms: i64,
    pub dirty: bool,
    pub created_at: Option<String>,
}

pub fn list_by_run(conn: &Connection, run_id: &str) -> Result<Vec<LapRecordEntity>, DbError> {
    let mut stmt = conn.prepare(
        "SELECT id, extraction_result_id, image_file_id, lap_index, driver, car, race_class,
                track, weather, temp_f, best_lap, best_lap_ms, dirty, created_at
          FROM lap_records WHERE run_id=?1 ORDER BY image_file_id, lap_index",
    )?;
    let rows = stmt.query_map(params![run_id], |row| {
        Ok(LapRecordEntity {
            id: row.get(0)?,
            extraction_result_id: row.get(1)?,
            image_file_id: row.get(2)?,
            lap_index: row.get::<_, i64>(3)?.try_into().unwrap_or(0),
            driver: row.get(4)?,
            car: row.get(5)?,
            race_class: row.get(6)?,
            track: row.get(7)?,
            weather: row.get(8)?,
            temp_f: row.get(9)?,
            best_lap: row.get(10)?,
            best_lap_ms: row.get(11)?,
            dirty: row.get::<_, i64>(12)? != 0,
            created_at: row.get(13)?,
        })
    })?;
    rows.collect::<Result<Vec<_>, _>>().map_err(DbError::from)
}

pub fn for_image_file(
    conn: &Connection,
    image_file_id: &str,
) -> Result<Vec<LapRecordEntity>, DbError> {
    let mut stmt = conn.prepare(
        "SELECT id, extraction_result_id, image_file_id, lap_index, driver, car, race_class,
                track, weather, temp_f, best_lap, best_lap_ms, dirty, created_at
          FROM lap_records WHERE image_file_id=?1 ORDER BY created_at DESC, lap_index",
    )?;
    let rows = stmt.query_map(params![image_file_id], |row| {
        Ok(LapRecordEntity {
            id: row.get(0)?,
            extraction_result_id: row.get(1)?,
            image_file_id: row.get(2)?,
            lap_index: row.get::<_, i64>(3)?.try_into().unwrap_or(0),
            driver: row.get(4)?,
            car: row.get(5)?,
            race_class: row.get(6)?,
            track: row.get(7)?,
            weather: row.get(8)?,
            temp_f: row.get(9)?,
            best_lap: row.get(10)?,
            best_lap_ms: row.get(11)?,
            dirty: row.get::<_, i64>(12)? != 0,
            created_at: row.get(13)?,
        })
    })?;
    rows.collect::<Result<Vec<_>, _>>().map_err(DbError::from)
}

#[derive(Debug, Clone)]
pub struct ExtractionResultEntity {
    pub id: String,
    pub run_id: String,
    pub image_file_id: String,
    pub status: String,
    pub error_type: Option<String>,
    pub error_message: Option<String>,
}

#[derive(Debug, Clone)]
pub struct LapRecordInsertWithRun {
    pub lap_index: i64,
    pub driver: String,
    pub car: String,
    pub race_class: String,
    pub track: String,
    pub weather: String,
    pub temp_f: f64,
    pub best_lap: String,
    pub best_lap_ms: i64,
    pub dirty: bool,
}

pub fn add_result(
    conn: &Connection,
    result: &ExtractionResultEntity,
    run_id: &str,
    image_file_id: &str,
    entries: &[LapRecordInsertWithRun],
) -> Result<Vec<LapRecordEntity>, DbError> {
    let extraction_result_id =
        if !result.id.is_empty() {
            result.id.clone()
        } else {
            let existing: Option<String> = match conn.query_row(
                "SELECT id FROM extraction_results WHERE run_id=?1 AND image_file_id=?2 LIMIT 1",
                params![run_id, image_file_id],
                |r| r.get::<_, String>(0),
            ) {
                Ok(id) => Some(id),
                Err(rusqlite::Error::QueryReturnedNoRows) => None,
                Err(e) => return Err(DbError::from(e)),
            };

            match existing {
                Some(id) => id,
                None => {
                    let new_id = format!(
                        "res-{:x}",
                        std::time::SystemTime::now()
                            .duration_since(std::time::UNIX_EPOCH)
                            .map(|d| d.as_nanos() as u64)
                            .unwrap_or(0)
                    );
                    // `extraction_results.run_input_id` is NOT NULL: create the
                    // owning `process` input first so this fallback insert is
                    // valid instead of always failing on the constraint.
                    let next_order: i64 = conn
                        .query_row(
                            "SELECT COALESCE(MAX(input_order), 0) + 1 FROM run_inputs WHERE run_id = ?1",
                            params![run_id],
                            |r| r.get(0),
                        )
                        .unwrap_or(1);
                    conn.execute(
                        "INSERT INTO run_inputs (run_id, image_file_id, decision, input_order, input_path, process_reason, created_at)
                         VALUES (?1, ?2, 'process', ?3, 'seed/path.png', 'full_run', datetime('now'))",
                        params![run_id, image_file_id, next_order],
                    )?;
                    let run_input_id: i64 = conn.last_insert_rowid();
                    conn.execute(
                        "INSERT INTO extraction_results
                        (id, run_id, run_input_id, image_file_id, status, created_at, updated_at)
                     VALUES (?1, ?2, ?3, ?4, 'ok', datetime('now'), datetime('now'))",
                        params![&new_id, run_id, run_input_id, image_file_id],
                    )?;
                    new_id
                }
            }
        };

    let mut created = Vec::new();

    for entry in entries {
        let exists: bool = conn.query_row(
            "SELECT COUNT(*) FROM lap_records WHERE extraction_result_id=?1 AND lap_index=?2",
            params![&extraction_result_id, entry.lap_index],
            |r| r.get::<_, i64>(0),
        )? > 0;

        if exists {
            continue;
        }

        // Id includes the result so reprocessing an image under a new result
        // never collides on the primary key (Python uses uuid4 for the same
        // reason; the (result, lap_index) guard keeps reruns idempotent).
        let id = format!("lap-{}-{}", extraction_result_id, entry.lap_index);
        let best_lap_clean = strip_dirty_symbol(&entry.best_lap);
        let driver_normalized = entry.driver.trim().to_lowercase();
        let car_normalized = entry.car.trim().to_lowercase();
        let track_normalized = entry.track.trim().to_lowercase();
        let temp_c = forza_domain::lap::fahrenheit_to_celsius(entry.temp_f, 40.0, 140.0);

        conn.execute(
            "INSERT INTO lap_records
                (id, run_id, image_file_id, extraction_result_id, lap_index,
                 driver, driver_normalized, car, car_normalized,
                 race_class, track, track_normalized, weather, temp_f, temp_c,
                 best_lap, best_lap_ms, dirty, created_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9,
                     ?10, ?11, ?12, ?13, ?14, ?15,
                     ?16, ?17, ?18, datetime('now'))",
            params![
                id,
                run_id,
                image_file_id,
                &extraction_result_id,
                entry.lap_index,
                &entry.driver,
                driver_normalized,
                &entry.car,
                car_normalized,
                &entry.race_class,
                &entry.track,
                track_normalized,
                &entry.weather,
                entry.temp_f,
                temp_c,
                best_lap_clean,
                entry.best_lap_ms,
                if entry.dirty { 1 } else { 0 },
            ],
        )?;

        created.push(LapRecordEntity {
            id: id.clone(),
            extraction_result_id: Some(extraction_result_id.clone()),
            image_file_id: image_file_id.to_string(),
            lap_index: entry.lap_index.try_into().unwrap_or(0),
            driver: entry.driver.clone(),
            car: entry.car.clone(),
            race_class: entry.race_class.clone(),
            track: entry.track.clone(),
            weather: entry.weather.clone(),
            temp_f: entry.temp_f,
            best_lap: best_lap_clean.clone(),
            best_lap_ms: entry.best_lap_ms,
            dirty: entry.dirty,
            created_at: None,
        });
    }

    Ok(created)
}

#[derive(Debug, Clone)]
pub struct ReviewCase {
    pub reason: String,
    pub trigger_name: String,
    pub lap_id: String,
    pub image_file_id: String,
    pub lap_index: i64,
    pub driver: String,
    pub track: String,
    pub race_class: String,
    pub weather: String,
    pub best_lap: Option<String>,
    pub car: String,
    pub best_lap_ms: i64,
}

pub fn append_rain_time_review_candidates(
    conn: &Connection,
    candidates: &mut Vec<ReviewCase>,
) -> Result<(), DbError> {
    let mut stmt = conn.prepare(
        "SELECT id, track, race_class, weather, best_lap_ms, image_file_id, lap_index,
                driver, best_lap, car
         FROM lap_records WHERE is_best_lap=1 ORDER BY track, race_class, weather, best_lap_ms",
    )?;

    // Nullable text columns degrade gracefully (unknown/empty) instead of
    // failing the whole candidate pass on one sparse row.
    let rows = stmt.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, Option<String>>(1)?.unwrap_or_default(),
            row.get::<_, Option<String>>(2)?.unwrap_or_default(),
            row.get::<_, Option<String>>(3)?.unwrap_or_else(|| "unknown".into()),
            row.get::<_, i64>(4)?,
            row.get::<_, String>(5)?,
            row.get::<_, i64>(6)?,
            row.get::<_, String>(7)?,
            row.get::<_, Option<String>>(8)?,
            // `car` is nullable in the schema: degrade to "" (the review
            // upserts a `car_empty` case from it when appropriate).
            row.get::<_, Option<String>>(9)?.unwrap_or_default(),
        ))
    })?;

    let laps: Vec<(
        String,
        String,
        String,
        String,
        i64,
        String,
        i64,
        String,
        Option<String>,
        String,
    )> = rows.collect::<Result<_, _>>()?;

    // Python compares the bucket minima (best rain vs best dry on the same
    // track/class) and then flags EVERY rain best-lap row of that bucket.
    let mut best_by_key: HashMap<(String, String, String), i64> = HashMap::new();
    for (_, track, race_class, weather, best_lap_ms, _, _, _, _, _) in &laps {
        let key = (track.clone(), race_class.clone(), weather.clone());
        match best_by_key.get(&key) {
            Some(current) if *current <= *best_lap_ms => {}
            _ => {
                best_by_key.insert(key, *best_lap_ms);
            }
        }
    }

    for (
        lap_id,
        track,
        race_class,
        weather,
        best_lap_ms,
        image_file_id,
        lap_index,
        driver,
        best_lap,
        car,
    ) in &laps
    {
        if !weather.eq_ignore_ascii_case("rain") {
            continue;
        }
        let rain_key = (track.clone(), race_class.clone(), "rain".to_string());
        let dry_key = (track.clone(), race_class.clone(), "dry".to_string());
        let best_rain = best_by_key.get(&rain_key);
        let best_dry = best_by_key.get(&dry_key);
        if let (Some(&best_rain), Some(&best_dry)) = (best_rain, best_dry)
            && best_rain < best_dry
        {
            candidates.push(ReviewCase {
                reason: "weather".to_string(),
                trigger_name: "rain_time_suspicious".to_string(),
                lap_id: lap_id.clone(),
                image_file_id: image_file_id.clone(),
                lap_index: *lap_index,
                driver: driver.clone(),
                track: track.clone(),
                race_class: race_class.clone(),
                weather: weather.clone(),
                best_lap: best_lap.clone(),
                car: car.clone(),
                best_lap_ms: *best_lap_ms,
            });
        }
    }

    Ok(())
}
