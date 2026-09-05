// Semantic-name stamping: the human-readable "Track - Class.ext" label must be
// persisted once laps are known (readers prefer it over current_name).
#![allow(clippy::unwrap_used, clippy::expect_used)]

use forza_app::services::extraction_runner::stamp_semantic_name;

fn seeded_db(dir: &tempfile::TempDir) -> rusqlite::Connection {
    let db = dir.path().join("sem.sqlite3");
    forza_db::upgrade(&db).unwrap();
    forza_db::open_connection(&db).unwrap()
}

#[test]
fn stamp_writes_track_dash_class_with_source_extension() {
    let dir = tempfile::tempdir().unwrap();
    let conn = seeded_db(&dir);
    conn.execute_batch(
        "INSERT INTO extraction_runs (id, status, mode, model, created_at)
         VALUES ('run-s', 'completed', 'normal', 'm', datetime('now'));
         INSERT INTO image_files (id, file_hash, current_name, first_seen_at, created_at, updated_at)
         VALUES ('img-s', 'h', 'shot.png', datetime('now'), datetime('now'), datetime('now'));
         INSERT INTO run_inputs (run_id, image_file_id, decision, input_order, input_path, created_at)
         VALUES ('run-s', 'img-s', 'process', 1, 'shot.png', datetime('now'));
         INSERT INTO extraction_results (id, run_id, run_input_id, image_file_id, status, created_at, updated_at)
         VALUES ('res-s', 'run-s', 1, 'img-s', 'ok', datetime('now'), datetime('now'));
         INSERT INTO lap_records (id, run_id, image_file_id, extraction_result_id, lap_index,
                                  track, race_class, created_at)
         VALUES ('lap-s', 'run-s', 'img-s', 'res-s', 0, 'Fuji Speedway', 'A', datetime('now'));",
    )
    .unwrap();

    stamp_semantic_name(
        &conn,
        "img-s",
        std::path::Path::new("some/dir/shot.png"),
        "res-s",
    );

    let name: Option<String> = conn
        .query_row(
            "SELECT semantic_name FROM image_files WHERE id = 'img-s'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(name.as_deref(), Some("Fuji Speedway - A.png"));
}

#[test]
fn stamp_without_laps_leaves_null() {
    let dir = tempfile::tempdir().unwrap();
    let conn = seeded_db(&dir);
    conn.execute_batch(
        "INSERT INTO extraction_runs (id, status, mode, model, created_at)
         VALUES ('run-n', 'completed', 'normal', 'm', datetime('now'));
         INSERT INTO image_files (id, file_hash, current_name, first_seen_at, created_at, updated_at)
         VALUES ('img-n', 'h', 'shot.png', datetime('now'), datetime('now'), datetime('now'));",
    )
    .unwrap();

    stamp_semantic_name(
        &conn,
        "img-n",
        std::path::Path::new("shot.png"),
        "res-missing",
    );

    let name: Option<String> = conn
        .query_row(
            "SELECT semantic_name FROM image_files WHERE id = 'img-n'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(name, None);
}
