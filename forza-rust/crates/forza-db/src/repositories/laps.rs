//! `lap_records` repository (insert path for seeds/tests).

use crate::error::DbError;
use rusqlite::{Connection, params};

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
