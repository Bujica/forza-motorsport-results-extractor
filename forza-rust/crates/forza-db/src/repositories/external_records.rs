//! External/community best-lap records: active snapshot read + replacement.

use rusqlite::{Connection, params};

use crate::error::DbError;

/// One active external best-lap record (lightweight projection for GUI/output).
#[derive(Debug, Clone, PartialEq)]
pub struct ExternalLapRecord {
    pub track: String,
    pub race_class: String,
    pub driver: String,
    pub car: String,
    pub best_lap: String,
    pub best_lap_ms: i64,
    pub source: String,
}

/// One import batch header (mirrors `external_record_imports`).
#[derive(Debug, Clone, PartialEq)]
pub struct ExternalRecordImport {
    pub id: String,
    pub source_path: String,
    pub source_hash: Option<String>,
    pub status: String,
    pub active: bool,
    pub total_rows: i64,
    pub accepted_rows: i64,
    pub rejected_rows: i64,
    pub issue_count: i64,
}

/// List active external records ordered for deterministic GUI/merge consumption.
pub fn list_active_external_records(conn: &Connection) -> Result<Vec<ExternalLapRecord>, DbError> {
    let mut stmt = conn.prepare(
        "SELECT track, race_class, driver, car, best_lap, best_lap_ms,
                (SELECT source_path FROM external_record_imports WHERE id = external_lap_records.import_id)
         FROM external_lap_records
         WHERE active = 1
         ORDER BY LOWER(track), race_class, best_lap_ms",
    )?;
    let rows = stmt.query_map([], |row| {
        Ok(ExternalLapRecord {
            track: row.get(0)?,
            race_class: row.get(1)?,
            driver: row.get(2)?,
            car: row.get(3)?,
            best_lap: row.get(4)?,
            best_lap_ms: row.get(5)?,
            source: row
                .get::<_, Option<String>>(6)?
                .unwrap_or_else(|| "External".to_string()),
        })
    })?;
    rows.collect::<Result<Vec<_>, _>>().map_err(DbError::from)
}

/// Replace the active external snapshot atomically.
///
/// `records` are the canonical best-by-group rows (already deduplicated).
/// `issues_json` is the serialized `ExternalImportResult.issues` list.
pub fn replace_active_snapshot(
    conn: &Connection,
    records: &[ExternalLapRecord],
    source_path: &str,
    source_hash: Option<&str>,
    total_rows: i64,
    rejected_rows: i64,
    issues_json: Option<&str>,
) -> Result<String, DbError> {
    let import_id = format!(
        "imp-{:x}",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos() as u64)
            .unwrap_or(0)
    );
    let accepted = i64::try_from(records.len()).unwrap_or(0);
    let issue_count = issues_json
        .and_then(|s| serde_json::from_str::<serde_json::Value>(s).ok())
        .and_then(|v| v.as_array().map(|a| i64::try_from(a.len()).unwrap_or(0)))
        .unwrap_or(0);

    // Atomic snapshot replacement — use explicit transaction so a failure doesn't leave
    // the DB with imports deactivated but no new rows. Never swallow BEGIN:
    // a COMMIT failure must propagate (caller was told nothing was replaced),
    // and running nested inside someone else's transaction would let our
    // ROLLBACK undo the caller's outer work.
    if !conn.is_autocommit() {
        return Err(DbError::SchemaState {
            message: "replace_active_snapshot requires autocommit (no outer transaction)".into(),
        });
    }
    conn.execute_batch("BEGIN IMMEDIATE").map_err(|e| DbError::Pool(format!("BEGIN IMMEDIATE: {e}")))?;
    let inner: Result<String, DbError> = (|| {
        conn.execute(
            "UPDATE external_record_imports SET active = 0 WHERE active = 1",
            [],
        )?;
        conn.execute(
            "INSERT INTO external_record_imports
                (id, source_path, source_hash, status, active, total_rows, accepted_rows, rejected_rows, issue_count, issues_json, created_at, imported_at, activated_at)
             VALUES (?1, ?2, ?3, 'active', 1, ?4, ?5, ?6, ?7, ?8, datetime('now'), datetime('now'), datetime('now'))",
            params![
                import_id,
                source_path,
                source_hash,
                total_rows,
                accepted,
                rejected_rows,
                issue_count,
                issues_json
            ],
        )?;
        // Deactivate old lap rows (keep history, but only new ones are active).
        conn.execute(
            "UPDATE external_lap_records SET active = 0 WHERE active = 1",
            [],
        )?;
        for rec in records {
            let lap_id = format!("ext-{}-{}-{}", import_id, rec.track, rec.race_class)
                .replace(' ', "_")
                .to_lowercase();
            // Ensure uniqueness across re-imports of same track/class (second import
            // reuses same import_id, so include driver hash fallback when needed).
            let lap_id = format!("{lap_id}-{:x}", {
                use std::collections::hash_map::DefaultHasher;
                use std::hash::{Hash, Hasher};
                let mut h = DefaultHasher::new();
                rec.driver.hash(&mut h);
                rec.car.hash(&mut h);
                h.finish()
            });
            conn.execute(
                "INSERT INTO external_lap_records
                    (id, import_id, track, track_normalized, race_class, driver, driver_normalized, car, car_normalized, weather, best_lap, best_lap_ms, active, created_at)
                 VALUES (?1, ?2, ?3, lower(?3), ?4, ?5, lower(?5), ?6, lower(?6), 'dry', ?7, ?8, 1, datetime('now'))",
                params![lap_id, import_id, rec.track, rec.race_class, rec.driver, rec.car, rec.best_lap, rec.best_lap_ms],
            )?;
        }
        Ok(import_id.clone())
    })();
    match inner {
        Ok(id) => {
            conn.execute_batch("COMMIT")
                .map_err(|e| DbError::Pool(format!("COMMIT snapshot: {e}")))?;
            Ok(id)
        }
        Err(e) => {
            let _ = conn.execute_batch("ROLLBACK");
            Err(e)
        }
    }
}

/// Lightweight helper: list all known reference track names (for alias validation).
pub fn list_reference_tracks(conn: &Connection) -> Result<Vec<String>, DbError> {
    let mut stmt =
        conn.prepare("SELECT name FROM reference_tracks WHERE active = 1 ORDER BY name")?;
    let rows = stmt.query_map([], |r| r.get::<_, String>(0))?;
    rows.collect::<Result<Vec<_>, _>>().map_err(DbError::from)
}

/// List all known reference car names.
pub fn list_reference_cars(conn: &Connection) -> Result<Vec<String>, DbError> {
    let mut stmt =
        conn.prepare("SELECT name FROM reference_cars WHERE active = 1 ORDER BY name")?;
    let rows = stmt.query_map([], |r| r.get::<_, String>(0))?;
    rows.collect::<Result<Vec<_>, _>>().map_err(DbError::from)
}

/// Insert new reference cars (ignore duplicates), used after import discovers new cars.
pub fn seed_reference_cars(conn: &Connection, cars: &[String]) -> Result<usize, DbError> {
    let mut inserted = 0usize;
    for car in cars {
        let clean = car.trim();
        if clean.is_empty() {
            continue;
        }
        let id = format!("car-{}", clean.to_lowercase().replace(' ', "_"));
        let changed = conn.execute(
            "INSERT OR IGNORE INTO reference_cars (id, name, normalized_name, active, created_at, updated_at)
             VALUES (?1, ?2, lower(?2), 1, datetime('now'), datetime('now'))",
            params![id, clean],
        )?;
        inserted += changed;
    }
    Ok(inserted)
}
