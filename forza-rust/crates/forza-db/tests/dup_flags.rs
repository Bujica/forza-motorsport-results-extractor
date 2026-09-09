// Duplicate-file flags: sync ensures one active flag per duplicate row and
// resolves it when the canonical link disappears (Python parity).
#![allow(clippy::unwrap_used, clippy::expect_used)]

use forza_db::repositories::sync_review_flags;

fn fresh_db() -> (tempfile::TempDir, rusqlite::Connection) {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("dupflags.sqlite3");
    forza_db::upgrade(&path).unwrap();
    let conn = forza_db::open_connection(&path).unwrap();
    (dir, conn)
}

fn seed_pair(conn: &rusqlite::Connection) {
    for (id, name, dup_of) in [
        ("img-canon", "c.png", None),
        ("img-dup", "d.png", Some("img-canon")),
    ] {
        conn.execute(
            "INSERT INTO image_files
                (id, file_hash, current_name, current_path, duplicate_of_image_file_id,
                 file_status, first_seen_at, last_seen_at, created_at, updated_at)
             VALUES (?1, 'hash-1', ?2, ?3, ?4, 'available',
                     datetime('now'), datetime('now'), datetime('now'), datetime('now'))",
            rusqlite::params![id, name, format!("/tmp/{name}"), dup_of],
        )
        .unwrap();
    }
}

fn active_dup_flags(conn: &rusqlite::Connection) -> Vec<(String, String, String)> {
    let mut stmt = conn
        .prepare(
            "SELECT image_file_id, flag_key, reason FROM image_flags
             WHERE flag_type = 'duplicate' AND status = 'active'",
        )
        .unwrap();
    stmt.query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap()
}

#[test]
fn sync_ensures_and_resolves_duplicate_flags() {
    let (_dir, conn) = fresh_db();
    seed_pair(&conn);

    let (ensured, _) = sync_review_flags(&conn).unwrap();
    assert!(ensured >= 1);
    assert_eq!(
        active_dup_flags(&conn),
        vec![(
            "img-dup".to_string(),
            "image:img-dup:duplicate".to_string(),
            "duplicate_file_hash".to_string(),
        )],
        "one active flag per duplicate row, Python key format",
    );

    // Canonical link removed: flag resolves instead of lingering active.
    conn.execute(
        "UPDATE image_files SET duplicate_of_image_file_id = NULL WHERE id = 'img-dup'",
        [],
    )
    .unwrap();
    sync_review_flags(&conn).unwrap();
    assert!(active_dup_flags(&conn).is_empty());
}

#[test]
fn duplicate_flag_cleanup_unblocks_row_delete() {
    let (_dir, conn) = fresh_db();
    seed_pair(&conn);
    sync_review_flags(&conn).unwrap();

    // Without flag cleanup the FK RESTRICT on image_flags would refuse.
    conn.execute(
        "DELETE FROM image_flags WHERE image_file_id = 'img-dup' AND flag_type = 'duplicate'",
        [],
    )
    .unwrap();
    let removed = conn
        .execute("DELETE FROM image_files WHERE id = 'img-dup'", [])
        .unwrap();
    assert_eq!(removed, 1);
}
