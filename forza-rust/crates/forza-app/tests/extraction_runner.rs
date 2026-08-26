// Runner harness: unwraps are idiomatic assertion helpers here.
#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::single_match_else,
    clippy::single_match
)]

//! Headless extraction runner: empty input completes immediately without
//! contacting LM Studio; cancel-before-start short-circuits.

use std::sync::atomic::AtomicBool;
use std::sync::{Arc, mpsc};

use forza_app::{RunEvent, RunParams, spawn_extraction};

fn params(db: &std::path::Path, input: &std::path::Path) -> RunParams {
    RunParams {
        database_file: db.to_path_buf(),
        input_dir: input.to_path_buf(),
        gamertag: "TestDriver".into(),
        force: false,
        url: "http://127.0.0.1:1/api/v1/chat".into(), // unreachable on purpose
        model: "unused".into(),
        max_tokens: 10,
        temperature: 0.0,
        timeout_connect: 1,
        timeout_read: 1,
        max_retries: 1,
        prompt_id: "user_header_shaped_v1".into(),
        context_length: 5000,
        reasoning_mode: Some("off".into()),
        max_width: 1600,
        encode_quality: 85,
        image_format: "png".into(),
        grayscale: true,
    }
}

#[test]
fn empty_input_finishes_without_model_contact() {
    let dir = tempfile::tempdir().unwrap();
    let db = dir.path().join("run.sqlite3");
    forza_db::upgrade(&db).unwrap();
    let input = dir.path().join("input");
    std::fs::create_dir(&input).unwrap();

    let (tx, rx) = mpsc::channel();
    let cancel = Arc::new(AtomicBool::new(false));
    let handle = spawn_extraction(params(&db, &input), cancel, move |event| {
        tx.send(event).unwrap();
    });

    let mut saw_finished = false;
    for _ in 0..10 {
        match rx.recv_timeout(std::time::Duration::from_secs(5)).unwrap() {
            RunEvent::Finished {
                cancelled,
                processed,
                ..
            } => {
                assert!(!cancelled);
                assert_eq!(processed, 0);
                saw_finished = true;
                break;
            }
            _ => {}
        }
    }
    assert!(saw_finished, "Finished event expected");
    handle.join().ok();
}

#[test]
fn cancel_before_spawn_yields_cancelled_finish() {
    let dir = tempfile::tempdir().unwrap();
    let db = dir.path().join("run.sqlite3");
    forza_db::upgrade(&db).unwrap();
    let input = dir.path().join("input");
    std::fs::create_dir(&input).unwrap();

    let (tx, rx) = mpsc::channel();
    let cancel = Arc::new(AtomicBool::new(true));
    let handle = spawn_extraction(params(&db, &input), cancel, move |event| {
        tx.send(event).unwrap();
    });

    let mut saw_cancelled = false;
    for _ in 0..10 {
        match rx.recv_timeout(std::time::Duration::from_secs(5)).unwrap() {
            RunEvent::Finished { cancelled, .. } => {
                assert!(cancelled);
                saw_cancelled = true;
                break;
            }
            _ => {}
        }
    }
    assert!(saw_cancelled);
    handle.join().ok();
}
