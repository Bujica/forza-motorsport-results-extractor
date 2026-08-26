// Test harness: unwraps are idiomatic assertion helpers here.
#![allow(clippy::unwrap_used, clippy::expect_used)]

//! GUI inventory query: derived processing status, filters, stable ordering,
//! and the basic DB doctor battery.

use forza_db::gui_queries::{ImageInventoryFilter, image_inventory};
use forza_db::test_support::seed_demo_database;
use rusqlite::Connection;

fn seeded() -> (tempfile::TempDir, Connection) {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("gui.sqlite3");
    forza_db::upgrade(&path).unwrap();
    let mut conn = forza_db::open_connection(&path).unwrap();
    seed_demo_database(&mut conn).unwrap();
    (dir, conn)
}

#[test]
fn inventory_projects_processing_status_from_latest_result() {
    let (_dir, conn) = seeded();
    let rows = image_inventory(&conn, &ImageInventoryFilter::default()).unwrap();

    assert_eq!(rows.len(), 2);
    for row in &rows {
        assert_eq!(row.processing_status, "processed_ok", "{row:?}");
    }
}

#[test]
fn inventory_filter_by_processing_status() {
    let (_dir, conn) = seeded();

    // A third image considered-and-skipped by the run: no result, non-process decision.
    conn.execute(
        "INSERT INTO image_files (id, file_hash, current_name, current_path, first_seen_at, last_seen_at, created_at, updated_at)
         VALUES ('img-skip', 'hs', 'skipped.png', 'p', datetime('now'), datetime('now'), datetime('now'), datetime('now'))",
        [],
    )
    .unwrap();
    conn.execute(
        "INSERT INTO run_inputs (id, run_id, image_file_id, decision, input_order, input_path, created_at)
         SELECT COALESCE(MAX(id), 0) + 1, '20260101_000000_seedrun', 'img-skip', 'duplicate', 9, 'seed/path.png', datetime('now') FROM run_inputs",
        [],
    )
    .unwrap();
    // Fourth image with no inputs at all.
    conn.execute(
        "INSERT INTO image_files (id, file_hash, current_name, current_path, first_seen_at, last_seen_at, created_at, updated_at)
         VALUES ('img-untouched', 'hu', 'untouched.png', 'p', datetime('now'), datetime('now'), datetime('now'), datetime('now'))",
        [],
    )
    .unwrap();

    let all = image_inventory(&conn, &ImageInventoryFilter::default()).unwrap();
    assert_eq!(all.len(), 4);

    let ok_only = image_inventory(
        &conn,
        &ImageInventoryFilter {
            processing_status: Some("processed_ok".into()),
            ..Default::default()
        },
    )
    .unwrap();
    assert_eq!(ok_only.len(), 2);

    let skipped = image_inventory(
        &conn,
        &ImageInventoryFilter {
            processing_status: Some("skipped".into()),
            ..Default::default()
        },
    )
    .unwrap();
    assert_eq!(skipped.len(), 1);
    assert_eq!(skipped[0].id, "img-skip");

    let unprocessed = image_inventory(
        &conn,
        &ImageInventoryFilter {
            processing_status: Some("unprocessed".into()),
            ..Default::default()
        },
    )
    .unwrap();
    assert_eq!(unprocessed.len(), 1);
    assert_eq!(unprocessed[0].id, "img-untouched");
}

#[test]
fn inventory_filter_by_run_id() {
    let (_dir, conn) = seeded();

    let rows = image_inventory(
        &conn,
        &ImageInventoryFilter {
            run_id: Some("20260101_000000_seedrun".into()),
            ..Default::default()
        },
    )
    .unwrap();
    assert_eq!(rows.len(), 2, "only images of the given run appear");
}

#[test]
fn inventory_ordering_is_stable_case_insensitive() {
    let (_dir, conn) = seeded();
    let first = image_inventory(&conn, &ImageInventoryFilter::default()).unwrap();
    let second = image_inventory(&conn, &ImageInventoryFilter::default()).unwrap();
    let names_a: Vec<String> = first.iter().map(|r| r.current_name.clone()).collect();
    let names_b: Vec<String> = second.iter().map(|r| r.current_name.clone()).collect();
    assert_eq!(
        names_a, names_b,
        "same query must produce identical ordering"
    );
    let mut sorted_names = names_a.clone();
    sorted_names.sort_by_key(|n| n.to_lowercase());
    assert_eq!(
        names_a.iter().map(|n| n.to_lowercase()).collect::<Vec<_>>(),
        sorted_names
    );
}

#[test]
fn missing_files_hidden_by_default_but_listable_on_demand() {
    let (_dir, conn) = seeded();
    conn.execute(
        "UPDATE image_files SET file_status='missing' WHERE id='img-b'",
        [],
    )
    .unwrap();

    let visible = image_inventory(&conn, &ImageInventoryFilter::default()).unwrap();
    assert_eq!(visible.len(), 1);

    let everything = image_inventory(
        &conn,
        &ImageInventoryFilter {
            include_missing_files: true,
            ..Default::default()
        },
    )
    .unwrap();
    assert_eq!(everything.len(), 2);
}
