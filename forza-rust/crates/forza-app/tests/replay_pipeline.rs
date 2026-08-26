// Replay harness: unwraps are idiomatic assertion helpers here.
#![allow(clippy::unwrap_used, clippy::expect_used)]

//! End-to-end replay of a recorded response through the whole pipeline:
//! parse → validate → attempts → result → laps (Fase 7 criterion).

use forza_app::services::extraction_replay::{
    ReplayOutcome, derive_and_insert_laps, replay_recorded_response,
};

fn first_fixture(kind_prefix: &str) -> (tempfile::TempDir, String, String) {
    let dir = tempfile::tempdir().unwrap();
    let src =
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/model_responses");
    let mut chosen: Option<(String, String)> = None;
    for entry in std::fs::read_dir(&src).unwrap() {
        let path = entry.unwrap().path();
        let name = path.file_name().unwrap().to_string_lossy().to_string();
        if name.starts_with(kind_prefix) && name.ends_with(".json") {
            let data = std::fs::read_to_string(&path).unwrap();
            chosen = Some((name, data));
            break;
        }
    }
    let (_name, data) = chosen.expect("fixture present");
    let value: serde_json::Value = serde_json::from_str(&data).unwrap();
    let raw = value["raw_response"].as_str().unwrap().to_string();
    (
        dir,
        raw,
        value["attempt_id"]
            .as_str()
            .unwrap_or("unknown")
            .to_string(),
    )
}

fn fresh_db(path: &std::path::Path) -> rusqlite::Connection {
    forza_db::upgrade(path).unwrap();
    forza_db::open_connection(path).unwrap()
}

#[test]
fn accepted_fixture_flows_through_parse_validate_and_persistence() {
    let fixture_guard = first_fixture("accepted_");
    let db_path = fixture_guard.0.path().join("replay.sqlite3");
    let mut conn = fresh_db(&db_path);

    // Seed run + image + pending result via the demo helpers.
    let run_id = forza_db::repositories::insert_run(
        &conn,
        &forza_db::repositories::RunInsert::demo("20260101_000000_replay"),
    )
    .unwrap();
    forza_db::repositories::images::insert_image_file(
        &conn,
        &forza_db::repositories::ImageFileInsert {
            id: "img-replay",
            file_hash: "abc123",
            current_name: "shot.png",
            current_path: r"C:\shots\shot.png",
            size_bytes: 4096,
            width_px: 3840,
            height_px: 2160,
        },
    )
    .unwrap();
    let result_id = forza_db::repositories::runs::insert_input_and_result(
        &conn,
        &run_id,
        "img-replay",
        "process",
        "running",
        1,
    )
    .unwrap();

    let outcome: ReplayOutcome = replay_recorded_response(
        &mut conn,
        &run_id,
        "img-replay",
        &result_id,
        &fixture_guard.1,
        "test-model",
    )
    .unwrap();

    assert!(outcome.accepted);
    assert!(outcome.lap_rows > 0, "laps derived from parsed entries");

    // Attempt row carries the full evidence payload.
    let attempt: (String, i64) = conn
        .query_row(
            "SELECT raw_response, duration_ms FROM extraction_attempts WHERE extraction_result_id=?1",
            rusqlite::params![result_id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .unwrap();
    assert_eq!(attempt.0, fixture_guard.1);

    // Result is finalized as ok with the accepted attempt linked.
    let (status, accepted_id): (String, Option<String>) = conn
        .query_row(
            "SELECT status, accepted_attempt_id FROM extraction_results WHERE id=?1",
            rusqlite::params![result_id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .unwrap();
    assert_eq!(status, "ok");
    assert!(accepted_id.is_some());

    // Laps carry normalized domain values from the embedded references.
    let track: String = conn
        .query_row(
            "SELECT DISTINCT track FROM lap_records WHERE run_id=?1",
            rusqlite::params![run_id],
            |r| r.get(0),
        )
        .unwrap();
    assert!(!track.is_empty());
}

#[test]
fn lap_projection_matches_python_filtering_and_session_class() {
    let guard = tempfile::tempdir().unwrap();
    let db_path = guard.path().join("projection.sqlite3");
    let conn = fresh_db(&db_path);
    let run_id = forza_db::repositories::insert_run(
        &conn,
        &forza_db::repositories::RunInsert::demo("20260101_000000_projection"),
    )
    .unwrap();
    forza_db::repositories::images::insert_image_file(
        &conn,
        &forza_db::repositories::ImageFileInsert {
            id: "img-projection",
            file_hash: "projection-hash",
            current_name: "projection.png",
            current_path: r"C:\shots\projection.png",
            size_bytes: 4096,
            width_px: 3840,
            height_px: 2160,
        },
    )
    .unwrap();
    let result_id = forza_db::repositories::runs::insert_input_and_result(
        &conn,
        &run_id,
        "img-projection",
        "process",
        "running",
        1,
    )
    .unwrap();

    let raw = r#"{
        "t":"Daytona International Speedway Sports Car Circuit",
        "tf":80,
        "w":"dry",
        "e":[
            {"dr":"▲ Driver One","ca":"MB #33 A45","cl":"PI 700 A","bl":"01:54.154"},
            {"dr":"Ignored","ca":"Honda #73 Civic","cl":"PI 700 A","bl":""},
            {"dr":"Driver Two","ca":"Honda #73 Civic","cl":"PI 700 A","bl":"01:55.000 ▲"}
        ]
    }"#;
    let parsed: serde_json::Value = serde_json::from_str(raw).unwrap();
    let lap_rows = derive_and_insert_laps(
        &conn,
        &run_id,
        "img-projection",
        &result_id,
        &parsed,
        Some("projection.png"),
    )
    .unwrap();

    assert_eq!(lap_rows, 2, "empty best_lap rows must be discarded");
    let rows: Vec<(i64, String, String, String)> = conn
        .prepare(
            "SELECT lap_index, driver, race_class, best_lap
             FROM lap_records WHERE run_id=?1 ORDER BY lap_index",
        )
        .unwrap()
        .query_map(rusqlite::params![run_id], |r| {
            Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?))
        })
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap();
    assert_eq!(
        rows,
        vec![
            (0, "Driver One".into(), "TCR".into(), "01:54.154".into()),
            (1, "Driver Two".into(), "TCR".into(), "01:55.000".into()),
        ]
    );
    let (dirty, raw_lap_json): (i64, String) = conn
        .query_row(
            "SELECT dirty, raw_lap_json FROM lap_records
             WHERE run_id=?1 AND lap_index=1",
            rusqlite::params![run_id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .unwrap();
    assert_eq!(dirty, 1);
    assert_eq!(
        serde_json::from_str::<serde_json::Value>(&raw_lap_json).unwrap(),
        serde_json::json!({"model_best_lap": "01:55.000 ▲"})
    );
}

#[test]
fn malformed_fixture_also_replays_cleanly_under_current_rules() {
    let fixture_guard = first_fixture("malformed_");
    let db_path = fixture_guard.0.path().join("replay-m.sqlite3");
    let mut conn = fresh_db(&db_path);

    let run_id = forza_db::repositories::insert_run(
        &conn,
        &forza_db::repositories::RunInsert::demo("20260101_000000_rm"),
    )
    .unwrap();
    forza_db::repositories::images::insert_image_file(
        &conn,
        &forza_db::repositories::ImageFileInsert {
            id: "img-rm",
            file_hash: "def456",
            current_name: "rm.png",
            current_path: r"C:\shots\rm.png",
            size_bytes: 2048,
            width_px: 1920,
            height_px: 1080,
        },
    )
    .unwrap();
    let result_id = forza_db::repositories::runs::insert_input_and_result(
        &conn, &run_id, "img-rm", "process", "running", 1,
    )
    .unwrap();

    let outcome = replay_recorded_response(
        &mut conn,
        &run_id,
        "img-rm",
        &result_id,
        &fixture_guard.1,
        "test-model",
    )
    .expect("historically malformed responses validate under current rules");

    assert!(outcome.accepted);
}
