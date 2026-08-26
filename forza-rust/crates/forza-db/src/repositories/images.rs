//! `image_files` repository: identity inserts and existence checks.

use std::collections::{HashMap, HashSet};

use crate::error::DbError;
use rusqlite::{Connection, params};

/// path -> stored hash for available files (drives existing/duplicate planning).
pub fn known_path_hashes(conn: &Connection) -> Result<HashMap<String, String>, DbError> {
    let mut stmt = conn.prepare(
        "SELECT current_path, file_hash FROM image_files WHERE file_status = 'available'",
    )?;
    let rows = stmt.query_map([], |row| {
        Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
    })?;
    let mut out = HashMap::new();
    for item in rows {
        let (path, hash) = item?;
        out.insert(path, hash);
    }
    Ok(out)
}

/// Distinct hashes already present in the inventory.
pub fn known_hashes(conn: &Connection) -> Result<HashSet<String>, DbError> {
    let mut stmt =
        conn.prepare("SELECT DISTINCT file_hash FROM image_files WHERE file_status = 'available'")?;
    let rows = stmt.query_map([], |row| row.get::<_, String>(0))?;
    let mut out = HashSet::new();
    for hash in rows {
        out.insert(hash?);
    }
    Ok(out)
}

/// Available images whose LATEST extraction result is still `error` —
/// the retry-errors selection (`list_failed_images_for_retry`).
/// Ordering: newest result first, first occurrence per image wins.
pub fn list_failed_images_for_retry(conn: &Connection) -> Result<Vec<(String, String)>, DbError> {
    let mut stmt = conn.prepare(
        "WITH latest AS (
             SELECT image_file_id, status,
                    ROW_NUMBER() OVER (
                        PARTITION BY image_file_id
                        ORDER BY created_at DESC, id DESC
                    ) AS result_rank
             FROM extraction_results
         )
         SELECT i.current_path, i.file_hash
         FROM image_files i
         JOIN latest l ON l.image_file_id = i.id AND l.result_rank = 1
         WHERE i.file_status = 'available' AND l.status = 'error'
         ORDER BY i.current_name, i.id",
    )?;
    let rows = stmt.query_map([], |row| {
        Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
    })?;
    rows.collect::<Result<Vec<_>, _>>().map_err(DbError::from)
}

pub struct ImageFileInsert<'a> {
    pub id: &'a str,
    pub file_hash: &'a str,
    pub current_name: &'a str,
    pub current_path: &'a str,
    pub size_bytes: i64,
    pub width_px: i64,
    pub height_px: i64,
}

pub fn insert_image_file(conn: &Connection, row: &ImageFileInsert<'_>) -> Result<(), DbError> {
    conn.execute(
        "INSERT INTO image_files
            (id, file_hash, current_name, current_path, size_bytes,
             width_px, height_px, image_format, mime_type,
             file_status, best_lap_status, first_seen_at, last_seen_at,
             created_at, updated_at)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, 'png', 'image/png',
                 'available', 'pending',
                 datetime('now'), datetime('now'),
                 datetime('now'), datetime('now'))",
        params![
            row.id,
            row.file_hash,
            row.current_name,
            row.current_path,
            row.size_bytes,
            row.width_px,
            row.height_px,
        ],
    )?;
    Ok(())
}
