// Output golden harness: unwraps are idiomatic assertion helpers.
#![allow(clippy::unwrap_used, clippy::expect_used)]

//! Output goldens: CSV bytes byte-identical to the Python writer, and the
//! PDF content plan structurally identical to `_build_data_map` + ordering.

use base64::Engine as _;
use forza_output::csv::{ExportRow, export_csv};
use forza_output::pdf::build_pdf_plan;

const GOLDEN: &str = include_str!("../../../fixtures/expected/output_golden.json");

fn synthetic_rows() -> Vec<ExportRow> {
    vec![
        ExportRow {
            track: "Fuji Speedway".into(),
            race_class: "A".into(),
            weather: Some("dry".into()),
            temp_f: Some(80.0),
            temp_c: Some(26.7),
            driver: "Rival One".into(),
            car: "BMW M4 GT3".into(),
            best_lap: Some("1:29.000".into()),
            best_lap_ms: Some(89000),
            dirty: false,
            source_file: None,
            race_date: None,
            image_format: None,
            width_px: None,
            height_px: None,
        },
        ExportRow {
            track: "Fuji Speedway".into(),
            race_class: "A".into(),
            weather: Some("dry".into()),
            temp_f: Some(80.0),
            temp_c: Some(26.7),
            driver: "TestDriver".into(),
            car: "Audi R8 LMS".into(),
            best_lap: Some("1:30.500 ▲".into()),
            best_lap_ms: Some(90500),
            dirty: true,
            source_file: Some("shot_player.png".into()),
            race_date: Some("2026-08-01".into()),
            image_format: Some("png".into()),
            width_px: Some(3840),
            height_px: Some(2160),
        },
        ExportRow {
            track: "Le Mans Full Circuit".into(),
            race_class: "TCR".into(),
            weather: Some("rain".into()),
            temp_f: Some(61.0),
            temp_c: Some(16.1),
            driver: "TestDriver".into(),
            car: "Honda #73 Civic".into(),
            best_lap: Some("2:05.123".into()),
            best_lap_ms: Some(125123),
            dirty: false,
            source_file: Some("shot_lm.png".into()),
            race_date: Some("2026-07-20".into()),
            image_format: Some("jpeg".into()),
            width_px: Some(1920),
            height_px: Some(1080),
        },
    ]
}

fn track_order() -> Vec<String> {
    // Same canonical source the Python side used (tracks.txt asset).
    include_str!("../../../assets/tracks.txt")
        .lines()
        .map(str::trim)
        .filter(|l| !l.is_empty())
        .map(ToOwned::to_owned)
        .collect()
}

#[test]
fn csv_bytes_are_identical_to_python_writer() {
    let golden = serde_json_json();
    let expected = base64::engine::general_purpose::STANDARD
        .decode(golden["csv_b64"].as_str().unwrap())
        .unwrap();

    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("out.csv");
    let n = export_csv(&synthetic_rows(), &path).unwrap();
    assert_eq!(n, 3);

    let got = std::fs::read(&path).unwrap();
    assert_eq!(
        got, expected,
        "CSV must be byte-identical (BOM, CRLF, quoting)"
    );
}

// serde_json is a dev-dependency; alias keeps call sites terse.
fn serde_json_json() -> serde_json::Value {
    serde_json::from_str(GOLDEN).unwrap()
}

#[test]
fn pdf_plan_matches_python_data_map_and_ordering() {
    let golden = serde_json_json();
    let plan = build_pdf_plan(&synthetic_rows(), "TestDriver", &track_order());
    let expected = &golden["pdf_plan"];

    assert_eq!(plan.gamertag, expected["gamertag"].as_str().unwrap());
    assert_eq!(
        plan.stats.tracks as u64,
        expected["stats"]["tracks"].as_u64().unwrap()
    );
    assert_eq!(
        plan.stats.classes as u64,
        expected["stats"]["classes"].as_u64().unwrap()
    );
    assert_eq!(
        plan.stats.laps as u64,
        expected["stats"]["laps"].as_u64().unwrap()
    );

    for (section, exp_section) in plan
        .sections
        .iter()
        .zip(expected["sections"].as_array().unwrap())
    {
        assert_eq!(section.track, exp_section["track"].as_str().unwrap());
        for (table, exp_table) in section
            .tables
            .iter()
            .zip(exp_section["tables"].as_array().unwrap())
        {
            assert_eq!(table.class, exp_table["class"].as_str().unwrap());
            assert_eq!(table.color_hex, exp_table["color_hex"].as_str().unwrap());
            for (row, exp_row) in table.rows.iter().zip(exp_table["rows"].as_array().unwrap()) {
                assert_eq!(row.driver, exp_row["driver"].as_str().unwrap());
                assert_eq!(row.car, exp_row["car"].as_str().unwrap());
                assert_eq!(row.time_str, exp_row["time_str"].as_str().unwrap());
                assert_eq!(row.time_ms, exp_row["time_ms"].as_i64().unwrap());
                assert_eq!(row.dirty, exp_row["dirty"].as_bool().unwrap());
                assert_eq!(row.mine, exp_row["mine"].as_bool().unwrap());
                if exp_row["temp"].is_null() {
                    assert!(row.temp_c.is_none());
                } else {
                    assert_eq!(row.temp_c.unwrap(), exp_row["temp"].as_f64().unwrap());
                }
            }
        }
    }
}
