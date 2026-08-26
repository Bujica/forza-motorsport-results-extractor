// Retry selection harness: unwraps are idiomatic assertion helpers here.
#![allow(clippy::unwrap_used, clippy::expect_used)]

//! `list_failed_images_for_retry`: only available images whose LATEST
//! extraction result is `error` are selected (Python retry-errors contract).

use forza_db::repositories::images::list_failed_images_for_retry;
use forza_db::repositories::runs::{RunInsert, insert_input_and_result, insert_run};

fn setup() -> (tempfile::TempDir, rusqlite::Connection) {
    let dir = tempfile::tempdir().unwrap();
    let db = dir.path().join("retry.sqlite3");
    forza_db::upgrade(&db).unwrap();
    let conn = forza_db::open_connection(&db).unwrap();
    (dir, conn)
}

fn seed_image(conn: &rusqlite::Connection, id: &str, hash: &str, status: &str) {
    forza_db::repositories::images::insert_image_file(
        conn,
        &forza_db::repositories::images::ImageFileInsert {
            id,
            file_hash: hash,
            current_name: &format!("{id}.png"),
            current_path: &format!(r"C:\shots\{id}.png"),
            size_bytes: 100,
            width_px: 100,
            height_px: 100,
        },
    )
    .unwrap();
    if status == "missing" {
        conn.execute(
            "UPDATE image_files SET file_status='missing' WHERE id=?1",
            rusqlite::params![id],
        )
        .unwrap();
    }
}

#[test]
fn only_latest_error_results_are_selected() {
    let (_guard, conn) = setup();
    let run_id = insert_run(&conn, &RunInsert::demo("20260101_000000_retry")).unwrap();

    seed_image(&conn, "img-ok", "hash-ok", "available");
    seed_image(&conn, "img-err", "hash-err", "available");
    seed_image(&conn, "img-missing", "hash-missing", "missing");

    // ok image: latest result is fine.
    insert_input_and_result(&conn, &run_id, "img-ok", "process", "ok", 1).unwrap();
    // error image: latest result failed.
    insert_input_and_result(&conn, &run_id, "img-err", "process", "error", 2).unwrap();
    // missing image: latest result failed but the file is gone.
    insert_input_and_result(&conn, &run_id, "img-missing", "process", "error", 3).unwrap();

    let selected = list_failed_images_for_retry(&conn).unwrap();
    assert_eq!(selected.len(), 1, "selected: {selected:?}");
    assert!(selected[0].0.contains("img-err"));
    assert_eq!(selected[0].1, "hash-err");
}

#[test]
fn older_ok_result_does_not_shadow_newer_error() {
    let (_guard, conn) = setup();
    let run_a = insert_run(&conn, &RunInsert::demo("20260101_000002_a")).unwrap();
    let run_b = insert_run(&conn, &RunInsert::demo("20260101_000002_b")).unwrap();

    seed_image(&conn, "img-x", "hash-x", "available");
    // First run: ok. Second run: error → the LATEST (error) must win.
    insert_input_and_result(&conn, &run_a, "img-x", "process", "ok", 1).unwrap();
    std::thread::sleep(std::time::Duration::from_millis(1100));
    insert_input_and_result(&conn, &run_b, "img-x", "process", "error", 1).unwrap();

    let selected = list_failed_images_for_retry(&conn).unwrap();
    assert_eq!(selected.len(), 1, "latest error must select the image");
}

#[test]
fn newer_ok_result_shadows_older_error() {
    let (_guard, conn) = setup();
    let run_a = insert_run(&conn, &RunInsert::demo("20260101_000003_a")).unwrap();
    let run_b = insert_run(&conn, &RunInsert::demo("20260101_000003_b")).unwrap();

    seed_image(&conn, "img-y", "hash-y", "available");
    insert_input_and_result(&conn, &run_a, "img-y", "process", "error", 1).unwrap();
    std::thread::sleep(std::time::Duration::from_millis(1100));
    insert_input_and_result(&conn, &run_b, "img-y", "process", "ok", 1).unwrap();

    let selected = list_failed_images_for_retry(&conn).unwrap();
    assert!(selected.is_empty(), "recovered images must not retry");
}
