//! `lap_records` repository: insert path plus the clean-flat export read model.

use crate::error::DbError;
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
                l.source_file, i.race_date, i.image_format, i.width_px, i.height_px
         FROM lap_records l
         LEFT JOIN image_files i ON i.id = l.image_file_id
         WHERE l.is_best_lap = 1
         ORDER BY LOWER(l.track), LOWER(l.race_class), LOWER(l.driver), l.best_lap_ms",
    )?;
    let rows = stmt.query_map([], |row| {
        let modified: Option<String> = row.get(11)?;
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
            race_date: modified
                .as_ref()
                .map(|m| m.get(..10).unwrap_or(m).to_string()),
            image_format: row.get(12)?,
            width_px: row.get(13)?,
            height_px: row.get(14)?,
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
