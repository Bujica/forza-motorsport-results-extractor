// Test harness: unwraps are idiomatic assertion helpers here.
#![allow(clippy::unwrap_used, clippy::expect_used)]

//! Constraint and relationship tests translated from
//! `forza-rust/docs/database.md` — the integrity invariants of the baseline.

use forza_db::repositories::{RunInsert, RunMetadata, insert_run, laps, runs, update_run_metadata};
use forza_db::repositories::{insert_image_file, insert_review_case};
use forza_db::test_support::seed_demo_database;
use rusqlite::{Connection, params};

fn fresh_db() -> (tempfile::TempDir, std::path::PathBuf, Connection) {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("constraints.sqlite3");
    forza_db::upgrade(&path).unwrap();
    let conn = forza_db::open_connection(&path).unwrap();
    (dir, path, conn)
}

#[test]
fn one_accepted_attempt_per_result_is_enforced() {
    let (_dir, _path, conn) = fresh_db();
    let run_id = insert_run(&conn, &RunInsert::demo("run-a")).unwrap();

    conn.execute(
        "INSERT INTO image_files (id, file_hash, current_name, current_path, first_seen_at, last_seen_at, created_at, updated_at)
         VALUES ('img-x', 'h', 'n', 'p', datetime('now'), datetime('now'), datetime('now'), datetime('now'))",
        [],
    )
    .unwrap();
    let result =
        runs::insert_input_and_result(&conn, &run_id, "img-x", "process", "ok", 1).unwrap();
    let first = runs::insert_accepted_attempt(&conn, &result, &run_id, "img-x").unwrap();

    let second = format!("att-2-{result}");
    let rejected = conn.execute(
        "INSERT INTO extraction_attempts
            (id, extraction_result_id, run_id, image_file_id, attempt_number, attempt_reason, status, accepted, created_at)
         VALUES (?1, ?2, ?3, ?4, 2, 'initial', 'ok', 1, datetime('now'))",
        params![second, result, run_id, "img-x"],
    );
    assert!(
        rejected.is_err(),
        "second accepted attempt must be rejected"
    );

    let third = format!("att-3-{result}");
    let retried = conn.execute(
        "INSERT INTO extraction_attempts
            (id, extraction_result_id, run_id, image_file_id, attempt_number, attempt_reason, status, accepted, created_at)
         VALUES (?1, ?2, ?3, ?4, 2, 'retry', 'error', 0, datetime('now'))",
        params![third, result, run_id, "img-x"],
    );
    assert!(retried.is_ok(), "non-accepted attempts remain allowed");
    let _ = first;
}

#[test]
fn live_run_metadata_replaces_seed_defaults() {
    let (_dir, _path, conn) = fresh_db();
    let run_id = insert_run(&conn, &RunInsert::demo("run-metadata")).unwrap();

    update_run_metadata(
        &conn,
        &run_id,
        &RunMetadata {
            backend: "lmstudio",
            model: "qwen3.6-35b-a3b",
            input_dir: r"C:\shots",
            prompt_name: "user_header_shaped_v1",
            prompt_hash: Some("prompt-sha256"),
            workers: 2,
            image_format: "webp",
            max_width: 1600,
            encode_quality: 85,
            grayscale: true,
            context_length: 32_768,
            reasoning_mode: Some("off"),
            max_completion_tokens: 2_048,
            temperature: 0.2,
            max_retries: 3,
            timeout_connect: 4,
            timeout_read: 90,
        },
    )
    .unwrap();

    let row = conn
        .query_row(
            "SELECT backend, model, input_dir, prompt_name, prompt_hash,
                    workers, image_format, max_width, encode_quality, grayscale,
                    context_length, reasoning_mode, max_completion_tokens,
                    temperature, max_retries, timeout_connect, timeout_read
             FROM extraction_runs WHERE id=?1",
            [&run_id],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, Option<String>>(4)?,
                    row.get::<_, i64>(5)?,
                    row.get::<_, String>(6)?,
                    row.get::<_, i64>(7)?,
                    row.get::<_, i64>(8)?,
                    row.get::<_, i64>(9)?,
                    row.get::<_, i64>(10)?,
                    row.get::<_, Option<String>>(11)?,
                    row.get::<_, i64>(12)?,
                    row.get::<_, f64>(13)?,
                    row.get::<_, i64>(14)?,
                    row.get::<_, i64>(15)?,
                    row.get::<_, i64>(16)?,
                ))
            },
        )
        .unwrap();

    assert_eq!(row.0, "lmstudio");
    assert_eq!(row.1, "qwen3.6-35b-a3b");
    assert_eq!(row.2, r"C:\shots");
    assert_eq!(row.3, "user_header_shaped_v1");
    assert_eq!(row.4.as_deref(), Some("prompt-sha256"));
    assert_eq!(row.5, 2);
    assert_eq!(row.6, "webp");
    assert_eq!(row.7, 1600);
    assert_eq!(row.8, 85);
    assert_eq!(row.9, 1);
    assert_eq!(row.10, 32_768);
    assert_eq!(row.11.as_deref(), Some("off"));
    assert_eq!(row.12, 2_048);
    assert!((row.13 - 0.2).abs() < f64::EPSILON);
    assert_eq!(row.14, 3);
    assert_eq!(row.15, 4);
    assert_eq!(row.16, 90);
}

#[test]
fn one_preflight_snapshot_per_run_is_enforced() {
    let (_dir, _path, conn) = fresh_db();
    let run_id = insert_run(&conn, &RunInsert::demo("run-b")).unwrap();

    let first = conn.execute(
        "INSERT INTO model_runtime_snapshots (id, run_id, snapshot_kind, endpoint, captured_at)
         VALUES ('snap-pf-1', ?1, 'preflight', 'http://127.0.0.1:1234', datetime('now'))",
        params![run_id],
    );
    assert!(first.is_ok(), "first preflight snapshot is accepted");

    let second = conn.execute(
        "INSERT INTO model_runtime_snapshots (id, run_id, snapshot_kind, endpoint, captured_at)
         VALUES ('snap-pf-2', ?1, 'preflight', 'http://127.0.0.1:1234', datetime('now'))",
        params![run_id],
    );
    assert!(
        second.is_err(),
        "idx_runtime_one_preflight_per_run must reject a second preflight"
    );

    let post = conn.execute(
        "INSERT INTO model_runtime_snapshots (id, run_id, snapshot_kind, endpoint, captured_at)
         VALUES ('snap-po-1', ?1, 'postflight', 'http://127.0.0.1:1234', datetime('now'))",
        params![run_id],
    );
    assert!(post.is_ok(), "non-preflight snapshots stay allowed");
}

#[test]
fn deleting_an_image_with_evidence_is_restricted() {
    let (_dir, _path, mut conn) = fresh_db();
    seed_demo_database(&mut conn).unwrap();

    let blocked = conn.execute("DELETE FROM image_files WHERE id = 'img-a'", []);
    assert!(blocked.is_err(), "RESTRICT FKs must block image deletion");

    let missing_only = conn.execute(
        "UPDATE image_files SET file_status='missing' WHERE id='img-a'",
        [],
    );
    assert!(missing_only.is_ok(), "marking missing stays allowed");
}

#[test]
fn deleting_a_run_cascades_through_the_evidence_tree() {
    let (_dir, _path, mut conn) = fresh_db();
    seed_demo_database(&mut conn).unwrap();

    conn.execute(
        "DELETE FROM extraction_runs WHERE id='20260101_000000_seedrun'",
        [],
    )
    .unwrap();

    for table in [
        "run_inputs",
        "extraction_results",
        "extraction_attempts",
        "lap_records",
    ] {
        let count: i64 = conn
            .query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |r| r.get(0))
            .unwrap();
        assert_eq!(count, 0, "{table} rows must cascade with their run");
    }
    let images: i64 = conn
        .query_row("SELECT COUNT(*) FROM image_files", [], |r| r.get(0))
        .unwrap();
    assert_eq!(images, 2, "images survive the run delete");
}

#[test]
fn duplicate_of_reference_set_null_on_canonical_delete() {
    let (_dir, _path, conn) = fresh_db();
    insert_image_file(
        &conn,
        &forza_db::repositories::ImageFileInsert {
            id: "canonical",
            file_hash: "hc",
            current_name: "a.png",
            current_path: r"C:\a.png",
            size_bytes: 1,
            width_px: 10,
            height_px: 10,
        },
    )
    .unwrap();
    insert_image_file(
        &conn,
        &forza_db::repositories::ImageFileInsert {
            id: "duplicate",
            file_hash: "hc",
            current_name: "b.png",
            current_path: r"C:\b.png",
            size_bytes: 1,
            width_px: 10,
            height_px: 10,
        },
    )
    .unwrap();
    conn.execute(
        "UPDATE image_files SET duplicate_of_image_file_id='canonical' WHERE id='duplicate'",
        [],
    )
    .unwrap();

    conn.execute("DELETE FROM image_files WHERE id='canonical'", [])
        .unwrap();

    let dangling: Option<String> = conn
        .query_row(
            "SELECT duplicate_of_image_file_id FROM image_files WHERE id='duplicate'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(
        dangling, None,
        "SET NULL detaches duplicates from deleted canonical"
    );
}

#[test]
fn vocabulary_checks_reject_invalid_values() {
    let (_dir, _path, conn) = fresh_db();

    let bad_status = conn.execute(
        "INSERT INTO extraction_runs (id, status, mode, model, created_at) VALUES ('r1', 'weird', 'normal', 'm', datetime('now'))",
        [],
    );
    assert!(bad_status.is_err(), "run status vocab must be enforced");

    let bad_mode = conn.execute(
        "INSERT INTO extraction_runs (id, status, mode, model, created_at) VALUES ('r2', 'pending', 'turbo', 'm', datetime('now'))",
        [],
    );
    assert!(bad_mode.is_err(), "run mode vocab must be enforced");

    let bad_attempt_rule = conn.execute(
        "INSERT INTO extraction_runs (id, status, mode, model, created_at) VALUES ('r3', 'pending', 'normal', 'm', datetime('now'))",
        [],
    );
    assert!(
        bad_attempt_rule.is_ok(),
        "plain pending run must be insertable: {bad_attempt_rule:?}"
    );

    let inconsistent = conn.execute(
        "INSERT INTO extraction_attempts (id, extraction_result_id, attempt_number, status, accepted)
         VALUES ('att-x', 'nope', 1, 'error', 1)",
        [],
    );
    assert!(
        inconsistent.is_err(),
        "(accepted=1 AND status<>'ok') violates ck_attempt_acceptance_status"
    );

    insert_image_file(
        &conn,
        &forza_db::repositories::ImageFileInsert {
            id: "img-v",
            file_hash: "hv",
            current_name: "v.png",
            current_path: r"C:\v.png",
            size_bytes: 5,
            width_px: 10,
            height_px: 10,
        },
    )
    .unwrap();
    let run_id = insert_run(&conn, &RunInsert::demo("run-v")).unwrap();
    let result =
        runs::insert_input_and_result(&conn, &run_id, "img-v", "process", "ok", 1).unwrap();
    let negative_lap = laps::insert_lap_record(
        &conn,
        &laps::LapRecordInsert {
            run_id: &run_id,
            image_file_id: "img-v",
            extraction_result_id: &result,
            attempt_id: None,
            lap_index: 1,
            driver: "D",
            car: "C",
            race_class: "A",
            track: "T",
            weather: "dry",
            temp_f: 80.0,
            best_lap: "-1",
            best_lap_ms: -50,
            dirty: false,
        },
    );
    assert!(
        negative_lap.is_err(),
        "best_lap_ms >= 0 check must reject negatives"
    );
}

#[test]
fn review_case_business_key_and_case_number_unique() {
    let (_dir, _path, mut conn) = fresh_db();
    seed_demo_database(&mut conn).unwrap();

    let base = forza_db::repositories::ReviewCaseInsert {
        business_key: "seed|case|1",
        case_number: 2,
        reason: "dirty_lap",
        trigger_name: Some("model_marked_dirty"),
        status: "open",
        outcome: "pending",
        image_file_id: Some("img-b"),
    };
    let dup_key = insert_review_case(&conn, &base);
    assert!(dup_key.is_err(), "business_key uniqueness enforced");

    let other = forza_db::repositories::ReviewCaseInsert {
        business_key: "other|key|9",
        case_number: 1,
        ..base
    };
    let dup_number = insert_review_case(&conn, &other);
    assert!(dup_number.is_err(), "case_number uniqueness enforced");
}

#[test]
fn lap_row_uniqueness_per_result_and_index() {
    let (_dir, _path, conn) = fresh_db();
    let run_id = insert_run(&conn, &RunInsert::demo("run-l")).unwrap();
    insert_image_file(
        &conn,
        &forza_db::repositories::ImageFileInsert {
            id: "img-l",
            file_hash: "hl",
            current_name: "l.png",
            current_path: r"C:\l.png",
            size_bytes: 9,
            width_px: 100,
            height_px: 100,
        },
    )
    .unwrap();
    let result =
        runs::insert_input_and_result(&conn, &run_id, "img-l", "process", "ok", 1).unwrap();
    let row = laps::LapRecordInsert {
        run_id: &run_id,
        image_file_id: "img-l",
        extraction_result_id: &result,
        attempt_id: None,
        lap_index: 7,
        driver: "d",
        car: "c",
        race_class: "B",
        track: "T",
        weather: "rain",
        temp_f: 70.0,
        best_lap: "1:40.0",
        best_lap_ms: 100_000,
        dirty: false,
    };
    laps::insert_lap_record(&conn, &row).unwrap();
    let second = laps::insert_lap_record(&conn, &row);
    assert!(
        second.is_err(),
        "(extraction_result_id, lap_index) uniqueness enforced"
    );
}
