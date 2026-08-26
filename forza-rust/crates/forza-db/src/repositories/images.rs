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
