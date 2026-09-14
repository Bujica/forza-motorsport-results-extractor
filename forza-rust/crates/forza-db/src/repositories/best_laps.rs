//! Best-lap frontier persistence: read rows, compute winners via the domain
//! calculator restricted to each image's latest run, and apply flags.

use std::collections::HashMap;

use rusqlite::{Connection, params};

use forza_domain::frontier::{clean_frontier_rows, simple_best_rows};
use forza_domain::ordering::LapRow;

#[derive(Debug, Clone)]
pub struct LapExportRow {
    pub id: String,
    pub image_file_id: String,
    pub run_id: String,
    pub track: String,
    pub race_class: String,
    pub weather: Option<String>,
    pub temp_f: Option<f64>,
    pub driver: String,
    pub car: String,
    pub best_lap_ms: Option<i64>,
    pub dirty: bool,
    pub lap_index: i64,
}

impl LapExportRow {
    fn load_all(conn: &Connection) -> Result<Vec<LapExportRow>, crate::DbError> {
        // Pre-sort only: display order is decided by
        // `forza_domain::ordering::ordered_lap_key` downstream, so this
        // spelling must never be relied on for pagination or output order.
        let mut stmt = conn.prepare(
            "SELECT id, image_file_id, run_id, track, race_class, weather, temp_f,
                    driver, car, best_lap_ms, dirty, lap_index
             FROM lap_records
             ORDER BY track, race_class, driver, best_lap_ms",
        )?;
        let rows = stmt.query_map([], |row| {
            Ok(LapExportRow {
                id: row.get(0)?,
                image_file_id: row.get(1)?,
                run_id: row.get(2)?,
                track: row.get(3)?,
                race_class: row.get(4)?,
                weather: row.get(5)?,
                temp_f: row.get(6)?,
                driver: row.get(7)?,
                car: row.get(8)?,
                best_lap_ms: row.get(9)?,
                dirty: row.get::<_, i64>(10)? != 0,
                lap_index: row.get(11)?,
            })
        })?;
        rows.collect::<Result<_, _>>().map_err(crate::DbError::from)
    }
}

impl LapRow for LapExportRow {
    fn id(&self) -> &str {
        &self.id
    }
    fn image_file_id(&self) -> &str {
        &self.image_file_id
    }
    fn track(&self) -> &str {
        &self.track
    }
    fn race_class(&self) -> &str {
        &self.race_class
    }
    fn weather(&self) -> Option<&str> {
        self.weather.as_deref()
    }
    fn temp_f(&self) -> Option<f64> {
        self.temp_f
    }
    fn driver(&self) -> &str {
        &self.driver
    }
    fn car(&self) -> &str {
        &self.car
    }
    fn best_lap_ms(&self) -> i64 {
        self.best_lap_ms.unwrap_or(i64::MAX)
    }
    fn dirty(&self) -> bool {
        self.dirty
    }
}

/// Keep only the most recent run's lap rows per image (run ids are
/// timestamp-prefixed so lexicographic max is the latest).
fn latest_rows_per_image(rows: &[LapExportRow]) -> Vec<&LapExportRow> {
    let mut latest_by_image: HashMap<&str, &str> = HashMap::new();
    for row in rows {
        let current = latest_by_image
            .entry(row.image_file_id.as_str())
            .or_insert("");
        if row.run_id.as_str() > *current {
            latest_by_image.insert(row.image_file_id.as_str(), &row.run_id);
        }
    }
    rows.iter()
        .filter(|row| latest_by_image.get(row.image_file_id.as_str()) == Some(&row.run_id.as_str()))
        .collect()
}

/// Recompute the best-lap frontier across the whole database.
///
/// With a gamertag this mirrors the clean-frontier semantics; without one it
/// falls back to the simple per-identity best. Returns winner lap ids.
pub fn mark_best_laps(
    conn: &Connection,
    gamertag: Option<&str>,
) -> Result<Vec<String>, crate::DbError> {
    let rows = LapExportRow::load_all(conn)?;
    // All-or-nothing: a crash between clear and set used to leave best-lap
    // flags half-cleared (wrong export until the next rebuild).
    // When called inside an outer transaction (e.g. full `rebuild`), the
    // caller owns atomicity and we run inline; otherwise manage our own txn.
    let owns_txn = conn.is_autocommit();
    if owns_txn {
        conn.execute_batch("BEGIN IMMEDIATE")?;
    }
    let outcome: Result<Vec<String>, crate::DbError> = (|| {
        // Batch clear: one UPDATE per id-chunk instead of one per row.
        let clear_ids: Vec<&str> = rows.iter().map(|r| r.id.as_str()).collect();
        for chunk in crate::id_chunks(&clear_ids) {
            let placeholders = crate::placeholders(chunk.len());
            let sql = format!("UPDATE lap_records SET is_best_lap=0 WHERE id IN ({placeholders})");
            let mut stmt = conn.prepare(&sql)?;
            stmt.execute(rusqlite::params_from_iter(chunk.iter()))?;
        }

        let candidates = latest_rows_per_image(&rows);
        let winners = match gamertag.filter(|g| !g.trim().is_empty()) {
            Some(tag) => clean_frontier_rows(&candidates, tag),
            None => simple_best_rows(&candidates)
                .into_iter()
                .map(|row| forza_domain::frontier::FrontierWinner {
                    id: row.id.clone(),
                    image_file_id: row.image_file_id.clone(),
                })
                .collect(),
        };

        let mut winner_image_ids: Vec<&str> = Vec::new();
        let winner_ids: Vec<&str> = winners.iter().map(|w| w.id.as_str()).collect();
        for chunk in crate::id_chunks(&winner_ids) {
            let placeholders = crate::placeholders(chunk.len());
            let sql = format!("UPDATE lap_records SET is_best_lap=1 WHERE id IN ({placeholders})");
            let mut stmt = conn.prepare(&sql)?;
            stmt.execute(rusqlite::params_from_iter(chunk.iter()))?;
        }
        for winner in &winners {
            winner_image_ids.push(winner.image_file_id.as_str());
        }

        // Update derived image status for every image touched by any candidate.
        let touched: std::collections::HashSet<&str> = candidates
            .iter()
            .map(|r| r.image_file_id.as_str())
            .collect();
        for image in touched {
            let contributing = winner_image_ids.contains(&image);
            conn.execute(
                "UPDATE image_files SET best_lap_status=?2 WHERE id=?1",
                params![
                    image,
                    if contributing {
                        "contributing"
                    } else {
                        "non_contributing"
                    }
                ],
            )?;
        }

        Ok(winners.into_iter().map(|w| w.id).collect())
    })();
    match outcome {
        Ok(ids) => {
            if owns_txn {
                conn.execute_batch("COMMIT")?;
            }
            Ok(ids)
        }
        Err(e) => {
            if owns_txn {
                let _ = conn.execute_batch("ROLLBACK");
            }
            Err(e)
        }
    }
}
