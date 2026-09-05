// Regression tests for P0-1: UPDATE placeholder mapping + NULL handling.
// Test harness: unwraps are idiomatic assertion helpers here.
#![allow(clippy::unwrap_used, clippy::expect_used)]

use forza_db::{open_connection, upgrade};
use forza_db::repositories::images::{UpsertParams, known_path_hashes, upsert_image_file};

fn fresh_conn() -> (tempfile::TempDir, rusqlite::Connection) {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("upsert.sqlite3");
    upgrade(&path).unwrap();
    let conn = open_connection(&path).unwrap();
    (dir, conn)
}

fn base_params(hash: &str) -> UpsertParams<'_> {
    UpsertParams {
        file_hash: hash,
        file_name: Some("shot_a.png"),
        current_path: Some("C:/shots/shot_a.png"),
        path: None,
        current_name: None,
        semantic_name: None,
        image_id: Some("img-a"),
        duplicate_of_image_file_id: None,
        best_lap_status: None,
        metadata_size_bytes: Some(10),
        metadata_format: None,
        metadata_mime_type: None,
        metadata_width_px: None,
        metadata_height_px: None,
        metadata_bit_depth: None,
        metadata_color_mode: None,
        metadata_file_modified_at: None,
        metadata_race_datetime: None,
        metadata_race_date: None,
        metadata_race_datetime_source: Some("file_modified_at"),
        metadata_image_metadata_json: None,
    }
}

#[test]
fn upsert_update_path_preserves_name_without_name_source() {
    let (_dir, conn) = fresh_conn();
    let entity = upsert_image_file(&conn, &base_params("hash-a")).unwrap();
    assert_eq!(entity.current_name, "shot_a.png");

    // Second upsert on the same id+hash with metadata only (no name material):
    // must not fail (placeholder regression) and must preserve the name.
    let mut p = base_params("hash-a");
    p.file_name = None;
    p.current_path = None;
    p.path = None;
    p.current_name = None;
    p.metadata_width_px = Some(1920);
    let entity2 = upsert_image_file(&conn, &p).unwrap();
    assert_eq!(entity2.id, "img-a");
    assert_eq!(entity2.current_name, "shot_a.png");
    assert_eq!(entity2.width_px, Some(1920));
}

#[test]
fn upsert_update_path_overwrites_name_with_explicit_source() {
    let (_dir, conn) = fresh_conn();
    upsert_image_file(&conn, &base_params("hash-b")).unwrap();

    let mut p = base_params("hash-b");
    p.current_name = Some("renamed.png");
    let entity = upsert_image_file(&conn, &p).unwrap();
    assert_eq!(entity.current_name, "renamed.png");
}

#[test]
fn known_path_hashes_skips_null_path_rows() {
    let (_dir, conn) = fresh_conn();
    upsert_image_file(&conn, &base_params("hash-c")).unwrap();
    conn.execute(
        "INSERT INTO image_files (id, file_hash, current_name, current_path, first_seen_at, last_seen_at, created_at, updated_at)
         VALUES ('img-null', 'hash-null', 'n.png', NULL, datetime('now'), datetime('now'), datetime('now'), datetime('now'))",
        [],
    )
    .unwrap();
    // Must not fail on the NULL current_path row.
    let _ = known_path_hashes(&conn).unwrap();
}
