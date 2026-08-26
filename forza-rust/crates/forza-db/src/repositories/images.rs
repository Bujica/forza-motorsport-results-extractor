//! `image_files` repository: identity inserts and existence checks.

use crate::error::DbError;
use rusqlite::{Connection, params};

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
