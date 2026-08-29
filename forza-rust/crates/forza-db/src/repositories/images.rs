//! `image_files` repository: identity inserts, existence checks, and full upsert.

use std::collections::{HashMap, HashSet};

use crate::error::DbError;
use rusqlite::{Connection, params};

/// path -> stored hash for available files (drives existing/duplicate planning).
pub fn known_path_hashes(conn: &Connection) -> Result<HashMap<String, String>, DbError> {
    let mut stmt = conn.prepare(
        "SELECT i.current_path, i.file_hash FROM image_files i
         WHERE i.file_status = 'available'
           AND EXISTS (SELECT 1 FROM extraction_results r
                       WHERE r.image_file_id = i.id
                         AND r.status IN ('ok', 'error'))",
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
    let mut stmt = conn.prepare(
        "SELECT DISTINCT i.file_hash FROM image_files i
         WHERE i.file_status = 'available'
           AND EXISTS (SELECT 1 FROM extraction_results r
                       WHERE r.image_file_id = i.id
                         AND r.status IN ('ok', 'error'))",
    )?;
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

pub struct UpsertParams<'a> {
    pub file_hash: &'a str,
    pub file_name: Option<&'a str>,
    pub current_path: Option<&'a str>,
    pub path: Option<&'a str>,
    pub current_name: Option<&'a str>,
    pub semantic_name: Option<&'a str>,
    pub image_id: Option<&'a str>,
    pub duplicate_of_image_file_id: Option<&'a str>,
    pub best_lap_status: Option<&'a str>,
    pub metadata_size_bytes: Option<i64>,
    pub metadata_format: Option<&'a str>,
    pub metadata_mime_type: Option<&'a str>,
    pub metadata_width_px: Option<u32>,
    pub metadata_height_px: Option<u32>,
    pub metadata_bit_depth: Option<u8>,
    pub metadata_color_mode: Option<&'a str>,
    pub metadata_file_modified_at: Option<&'a str>,
    pub metadata_race_datetime: Option<&'a str>,
    pub metadata_race_date: Option<&'a str>,
    pub metadata_race_datetime_source: Option<&'a str>,
    pub metadata_image_metadata_json: Option<&'a str>,
}

pub struct ImageFileEntity {
    pub id: String,
    pub file_hash: String,
    pub current_path: String,
    pub current_name: String,
    pub semantic_name: String,
    pub file_status: String,
    pub best_lap_status: Option<String>,
    pub duplicate_of_image_file_id: Option<String>,
    pub size_bytes: Option<i64>,
    pub image_format: Option<String>,
    pub mime_type: Option<String>,
    pub width_px: Option<u32>,
    pub height_px: Option<u32>,
    pub bit_depth: Option<u8>,
    pub color_mode: Option<String>,
}

fn resolve_path_conflict(conn: &Connection, path: &str, hash: &str) -> Result<(), DbError> {
    conn.execute(
        "UPDATE image_files
         SET file_status='missing', missing_at=datetime('now'), updated_at=datetime('now')
         WHERE current_path=?1 AND file_hash!=?2 AND file_status='available'",
        params![path, hash],
    )?;
    Ok(())
}

fn resolve_current_name(params: &UpsertParams) -> String {
    if let Some(name) = params.current_name {
        return name.to_string();
    }
    if let Some(path) = params.current_path.or(params.path)
        && !path.is_empty()
        && let Some(basename) = std::path::Path::new(path).file_name()
        && let Some(name) = basename.to_str()
    {
        return name.to_string();
    }
    if let Some(name) = params.file_name {
        return name.to_string();
    }
    "image".to_string()
}

fn resolve_current_path(params: &UpsertParams) -> String {
    match (params.current_path, params.path) {
        (Some(p), _) if !p.is_empty() => p.to_string(),
        (_, Some(p)) if !p.is_empty() => p.to_string(),
        _ => "".to_string(),
    }
}

pub fn upsert_image_file(
    conn: &Connection,
    params: &UpsertParams,
) -> Result<ImageFileEntity, DbError> {
    let resolved_path = resolve_current_path(params);
    let resolved_name = resolve_current_name(params);

    if !resolved_path.is_empty() {
        resolve_path_conflict(conn, &resolved_path, params.file_hash)?;
    }

    // Python `_existing_physical_file`: an existing row only represents the
    // same physical file when its stored hash matches; otherwise a new row is
    // created (the old owner was retired by the path-conflict step above).
    let existing_id: Option<String> = match params.image_id {
        Some(id) => conn
            .query_row(
                "SELECT id FROM image_files WHERE id=?1 AND file_hash=?2",
                params![id, params.file_hash],
                |r| r.get::<_, String>(0),
            )
            .ok(),
        None => None,
    };

    let existing_path: Option<String> = if existing_id.is_none() && !resolved_path.is_empty() {
        conn.query_row(
            "SELECT id FROM image_files WHERE current_path=?1 AND file_hash=?2 LIMIT 1",
            params![resolved_path.as_str(), params.file_hash],
            |r| r.get::<_, String>(0),
        )
        .ok()
    } else {
        None
    };

    let entity_id = existing_id
        .clone()
        .or(existing_path.clone())
        .unwrap_or_else(|| {
            params.image_id.map(|s| s.to_string()).unwrap_or_else(|| {
                format!(
                    "img-{:x}",
                    std::time::SystemTime::now()
                        .duration_since(std::time::UNIX_EPOCH)
                        .map(|d| d.as_nanos() as u64)
                        .unwrap_or(0)
                )
            })
        });

    let existing = existing_id.or(existing_path);

    if let Some(existing) = existing {
        let path_exists = !resolved_path.is_empty() && std::fs::metadata(&resolved_path).is_ok();
        let file_status = if path_exists { "available" } else { "missing" };

        let mut stmt = conn.prepare(
            "UPDATE image_files SET
                current_name=COALESCE(?2, current_name),
                semantic_name=COALESCE(?3, semantic_name),
                best_lap_status=COALESCE(?4, best_lap_status),
                size_bytes=COALESCE(?5, size_bytes),
                image_format=COALESCE(?6, image_format),
                mime_type=COALESCE(?7, mime_type),
                width_px=COALESCE(?8, width_px),
                height_px=COALESCE(?9, height_px),
                bit_depth=COALESCE(?10, bit_depth),
                color_mode=COALESCE(?11, color_mode),
                duplicate_of_image_file_id=COALESCE(?12, duplicate_of_image_file_id),
                file_modified_at=COALESCE(?13, file_modified_at),
                race_datetime=COALESCE(?14, race_datetime),
                race_date=COALESCE(?15, race_date),
                race_datetime_source=COALESCE(?16, race_datetime_source),
                image_metadata_json=COALESCE(?17, image_metadata_json),
                file_status=?19,
                missing_at=CASE WHEN ?19 = 'available' THEN NULL
                                ELSE COALESCE(missing_at, datetime('now')) END,
                updated_at=datetime('now')
             WHERE id=?18",
        )?;

        stmt.execute(params![
            resolved_name.as_str(),
            params.semantic_name,
            params.best_lap_status,
            params.metadata_size_bytes,
            params.metadata_format,
            params.metadata_mime_type,
            params.metadata_width_px.map(|v| v as i64),
            params.metadata_height_px.map(|v| v as i64),
            params.metadata_bit_depth.map(|v| v as i32),
            params.metadata_color_mode,
            params.duplicate_of_image_file_id,
            params.metadata_file_modified_at,
            params.metadata_race_datetime,
            params.metadata_race_date,
            params.metadata_race_datetime_source,
            params.metadata_image_metadata_json,
            &existing,
            file_status,
        ])?;

        let mut stmt_get = conn.prepare(
            "SELECT id, file_hash, current_path, current_name, semantic_name,
                    file_status, best_lap_status, duplicate_of_image_file_id,
                    size_bytes, image_format, mime_type, width_px, height_px, bit_depth, color_mode
             FROM image_files WHERE id=?1",
        )?;

        let entity = stmt_get.query_row(params![&existing], |row| {
            Ok(ImageFileEntity {
                id: row.get(0)?,
                file_hash: row.get(1)?,
                current_path: row.get(2)?,
                current_name: row.get(3)?,
                semantic_name: row.get(4)?,
                file_status: row.get(5)?,
                best_lap_status: row.get(6)?,
                duplicate_of_image_file_id: row.get(7)?,
                size_bytes: row.get(8)?,
                image_format: row.get(9)?,
                mime_type: row.get(10)?,
                width_px: row.get::<_, i64>(11)?.try_into().ok(),
                height_px: row.get::<_, i64>(12)?.try_into().ok(),
                bit_depth: row.get::<_, i32>(13)?.try_into().ok(),
                color_mode: row.get(14)?,
            })
        })?;

        Ok(entity)
    } else {
        let id = entity_id.clone();
        conn.execute(
            "INSERT INTO image_files
                (id, file_hash, current_name, current_path, semantic_name,
                 size_bytes, width_px, height_px, bit_depth, color_mode,
                 image_format, mime_type, file_status, best_lap_status,
                 duplicate_of_image_file_id,
                 file_modified_at, race_datetime, race_date, race_datetime_source,
                 image_metadata_json,
                 first_seen_at, last_seen_at, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12,
                     'available', COALESCE(?13, 'pending'), ?14,
                     ?15, ?16, ?17, ?18, ?19,
                     datetime('now'), datetime('now'), datetime('now'), datetime('now'))",
            params![
                id,
                params.file_hash,
                resolved_name.as_str(),
                resolved_path.as_str(),
                params.semantic_name,
                params.metadata_size_bytes,
                params.metadata_width_px.map(|v| v as i64),
                params.metadata_height_px.map(|v| v as i64),
                params.metadata_bit_depth.map(|v| v as i32),
                params.metadata_color_mode,
                params.metadata_format,
                params.metadata_mime_type,
                params.best_lap_status,
                params.duplicate_of_image_file_id,
                params.metadata_file_modified_at,
                params.metadata_race_datetime,
                params.metadata_race_date,
                params.metadata_race_datetime_source,
                params.metadata_image_metadata_json,
            ],
        )?;

        let entity = ImageFileEntity {
            id,
            file_hash: params.file_hash.to_string(),
            current_path: resolved_path,
            current_name: resolved_name,
            semantic_name: params
                .semantic_name
                .map(|s| s.to_string())
                .unwrap_or_default(),
            file_status: "available".to_string(),
            best_lap_status: None,
            duplicate_of_image_file_id: params.duplicate_of_image_file_id.map(|s| s.to_string()),
            size_bytes: params.metadata_size_bytes,
            image_format: params.metadata_format.map(|s| s.to_string()),
            mime_type: params.metadata_mime_type.map(|s| s.to_string()),
            width_px: params.metadata_width_px,
            height_px: params.metadata_height_px,
            bit_depth: params.metadata_bit_depth,
            color_mode: params.metadata_color_mode.map(|s| s.to_string()),
        };

        Ok(entity)
    }
}
