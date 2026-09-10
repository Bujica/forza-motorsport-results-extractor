// Car review → reference catalog: confirming a novel car seeds it, so later
// images with the same car no longer open review cases.
#![allow(clippy::unwrap_used, clippy::expect_used)]

use forza_app::services::review_queue::decide_case;

fn seed_db(path: &std::path::Path) -> rusqlite::Connection {
    forza_db::upgrade(path).unwrap();
    let conn = forza_db::open_connection(path).unwrap();
    conn.execute_batch(
        "INSERT INTO extraction_runs (id, status, mode, model, created_at)
         VALUES ('run-car', 'completed', 'normal', 'm', datetime('now'));
         INSERT INTO image_files (id, file_hash, first_seen_at, created_at, updated_at)
         VALUES ('img-car', 'hash-car', datetime('now'), datetime('now'), datetime('now'));
         INSERT INTO run_inputs (id, run_id, input_order, input_path, decision, created_at)
         VALUES (1, 'run-car', 0, 'c.png', 'process', datetime('now'));
         INSERT INTO extraction_results (id, run_id, run_input_id, image_file_id, status,
                                         created_at)
         VALUES ('res-car', 'run-car', 1, 'img-car', 'ok', datetime('now'));
         INSERT INTO lap_records (id, run_id, image_file_id, extraction_result_id,
                                  lap_index, weather, track, race_class, driver, car,
                                  best_lap, best_lap_ms, dirty, created_at)
         VALUES ('lap-car', 'run-car', 'img-car', 'res-car', 0, 'dry', 'Fuji Speedway',
                 'A', 'Driver One', 'Cadillac #3 ATS', '1:30.000', 90000, 0, datetime('now'));",
    )
    .unwrap();
    conn
}

fn car_case_numbers(conn: &rusqlite::Connection) -> Vec<i64> {
    conn.prepare("SELECT case_number FROM review_cases WHERE reason = 'car' AND status = 'open'")
        .unwrap()
        .query_map([], |r| r.get(0))
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap()
}

#[test]
fn confirmed_car_enters_reference_and_suppresses_future_cases() {
    let dir = tempfile::tempdir().unwrap();
    let mut conn = seed_db(&dir.path().join("car.sqlite3"));

    // Unknown car opens a case.
    let candidates = forza_db::repositories::query_review_candidates(&conn).unwrap();
    assert!(candidates.iter().any(|c| c.reason == "car"));
    let (inserted, _, _) = forza_db::repositories::upsert_review_cases(&conn, &candidates).unwrap();
    assert!(inserted >= 1);
    let cases = car_case_numbers(&conn);
    assert_eq!(cases.len(), 1);

    // Confirming seeds the catalog (idempotent on repeat).
    decide_case(&mut conn, cases[0], "car", "Cadillac #3 ATS").unwrap();
    decide_case(&mut conn, cases[0], "car", "Cadillac #3 ATS").unwrap();
    let seeded: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM reference_cars WHERE normalized_name = 'cadillac #3 ats'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(seeded, 1);

    // Same car on a new image: no new car case (pre-existing rows resolve).
    conn.execute(
        "INSERT INTO lap_records (id, run_id, image_file_id, extraction_result_id,
                                  lap_index, weather, track, race_class, driver, car,
                                  best_lap, best_lap_ms, dirty, created_at)
         VALUES ('lap-car2', 'run-car', 'img-car', 'res-car', 1, 'dry', 'Fuji Speedway',
                 'A', 'Driver Two', 'Cadillac #3 ATS', '1:31.000', 91000, 0, datetime('now'));",
        [],
    )
    .unwrap();
    let again = forza_db::repositories::query_review_candidates(&conn).unwrap();
    assert!(
        !again.iter().any(|c| c.reason == "car"),
        "confirmed car must not reopen cases: {:?}",
        again.iter().map(|c| &c.reason).collect::<Vec<_>>()
    );
}

#[test]
fn review_list_resolves_current_lap_per_case() {
    use forza_app::services::review_queue::{ReviewQueueFilter, list_review_cases};

    let dir = tempfile::tempdir().unwrap();
    let conn = seed_db(&dir.path().join("lap.sqlite3"));
    // Case linked to the lap row, and case with only image + index.
    conn.execute_batch(
        "INSERT INTO review_cases (id, business_key, case_number, reason, status, outcome,
                                   image_file_id, lap_record_id, lap_index, car,
                                   created_at, updated_at)
         VALUES ('rc-lap', 'car:img-car:0', 7, 'car', 'open', 'pending',
                 'img-car', 'lap-car', 0, 'Cadillac #3 ATS',
                 datetime('now'), datetime('now'));
         INSERT INTO review_cases (id, business_key, case_number, reason, status, outcome,
                                   image_file_id, lap_index, car, created_at, updated_at)
         VALUES ('rc-idx', 'car:img-car:1', 8, 'car', 'open', 'pending',
                 'img-car', 0, 'Cadillac #3 ATS', datetime('now'), datetime('now'));",
    )
    .unwrap();

    let filter = ReviewQueueFilter {
        bucket: "open".to_string(),
        reason: None,
        outcome: None,
        run_id: None,
        image_file_id: None,
    };
    let entries = list_review_cases(&conn, &filter).unwrap();
    assert_eq!(entries.len(), 2);
    for entry in &entries {
        // Seed lap is clean 1:30.000.
        assert_eq!(entry.current_best_lap.as_deref(), Some("1:30.000"));
        assert_eq!(entry.current_lap_dirty, Some(false));
    }
}
