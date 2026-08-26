//! Minimal insert/read repositories needed by tests, the GUI inventory
//! query, and CLI maintenance commands. Fuller repositories land with their
//! consuming phases (runs/review in Fase 8).

pub mod best_laps;
pub mod corrections;
pub mod images;
pub mod laps;
pub mod reviews;
pub mod runs;

pub use best_laps::mark_best_laps;
pub use corrections::apply_manual_correction;
pub use images::{ImageFileInsert, insert_image_file, known_hashes, known_path_hashes};
pub use laps::{LapRecordInsert, insert_lap_record};
pub use reviews::{
    ReviewCaseInsert, insert_review_case, query_review_candidates, upsert_review_cases,
};
pub use runs::{RunInsert, insert_run};

use crate::error::DbError;
use rusqlite::Connection;

/// Populate a fresh database with a small, coherent demo graph:
/// one run -> two inputs/results (one accepted attempt each) -> laps,
/// plus one open review case. Used to make constraint/query tests and
/// doctor checks reproducible.
pub fn seed_demo_database(conn: &mut Connection) -> Result<(), DbError> {
    let run = RunInsert::demo("20260101_000000_seedrun");
    let run_id = runs::insert_run(conn, &run)?;

    let img_a = "img-a";
    let img_b = "img-b";
    images::insert_image_file(
        conn,
        &ImageFileInsert {
            id: img_a,
            file_hash: "hash-a",
            current_name: "screenshot_a.png",
            current_path: r"C:\shots\screenshot_a.png",
            size_bytes: 1024,
            width_px: 3840,
            height_px: 2160,
        },
    )?;
    images::insert_image_file(
        conn,
        &ImageFileInsert {
            id: img_b,
            file_hash: "hash-b",
            current_name: "screenshot_b.png",
            current_path: r"C:\shots\screenshot_b.png",
            size_bytes: 2048,
            width_px: 3840,
            height_px: 2160,
        },
    )?;

    let result_a = runs::insert_input_and_result(conn, &run_id, img_a, "process", "ok", 1)?;
    let _result_b = runs::insert_input_and_result(conn, &run_id, img_b, "process", "ok", 2)?;
    let attempt_a = runs::insert_accepted_attempt(conn, &result_a, &run_id, img_a)?;
    let attempt_b = runs::insert_accepted_attempt(conn, &_result_b, &run_id, img_b)?;

    laps::insert_lap_record(
        conn,
        &LapRecordInsert {
            run_id: &run_id,
            image_file_id: img_a,
            extraction_result_id: &result_a,
            attempt_id: Some(&attempt_a),
            lap_index: 1,
            driver: "Player One",
            car: "Audi R8 LMS",
            race_class: "A",
            track: "Fuji Speedway",
            weather: "dry",
            temp_f: 82.0,
            best_lap: "1:32.500",
            best_lap_ms: 92_500,
            dirty: false,
        },
    )?;
    laps::insert_lap_record(
        conn,
        &LapRecordInsert {
            run_id: &run_id,
            image_file_id: img_b,
            extraction_result_id: &_result_b,
            attempt_id: Some(&attempt_b),
            lap_index: 1,
            driver: "Rival Driver",
            car: "BMW M4 GT3",
            race_class: "A",
            track: "Fuji Speedway",
            weather: "dry",
            temp_f: 82.0,
            best_lap: "1:31.900",
            best_lap_ms: 91_900,
            dirty: false,
        },
    )?;

    reviews::insert_review_case(
        conn,
        &ReviewCaseInsert {
            business_key: "seed|case|1",
            case_number: 1,
            reason: "dirty_lap",
            trigger_name: Some("model_marked_dirty"),
            status: "open",
            outcome: "pending",
            image_file_id: Some(img_a),
        },
    )?;
    Ok(())
}
