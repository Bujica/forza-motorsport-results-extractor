// Runner harness: unwraps are idiomatic assertion helpers here.
#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::single_match_else,
    clippy::single_match
)]

//! Headless extraction runner: empty input completes immediately without
//! contacting LM Studio; cancel-before-start short-circuits; pause blocks
//! between images and cancel lifts it; retry-errors selects failed images
//! only and refuses to combine with force.

use std::sync::mpsc;

use forza_app::{RunControl, RunEvent, RunParams, spawn_extraction};

fn params(db: &std::path::Path, input: &std::path::Path) -> RunParams {
    RunParams {
        database_file: db.to_path_buf(),
        input_dir: input.to_path_buf(),
        gamertag: "TestDriver".into(),
        force: false,
        retry_errors: false,
        selected_image_file_ids: None,
        max_images: None,
        workers: 1,
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
        eval_batch_size: Some(1024),
        physical_batch_size: None,
        flash_attention: true,
        offload_kv_cache_to_gpu: true,
        temp_min_f: 40.0,
        temp_max_f: 140.0,
        verbose: false,
        log_file: db.with_extension("log"),
        max_width: 1600,
        encode_quality: 85,
        image_format: "png".into(),
        grayscale: true,
        app_version: "test".to_string(),
    }
}

fn seeded(dir: &tempfile::TempDir) -> (std::path::PathBuf, std::path::PathBuf) {
    let db = dir.path().join("run.sqlite3");
    forza_db::upgrade(&db).unwrap();
    let input = dir.path().join("input");
    std::fs::create_dir(&input).unwrap();
    (db, input)
}

fn spawn(
    params: RunParams,
    control: RunControl,
) -> (mpsc::Receiver<RunEvent>, std::thread::JoinHandle<()>) {
    let (tx, rx) = mpsc::channel();
    let handle = spawn_extraction(params, control, move |event| {
        tx.send(event).unwrap();
    });
    (rx, handle)
}

fn wait_finished(rx: &mpsc::Receiver<RunEvent>) -> (bool, usize, Vec<String>) {
    let mut logs = Vec::new();
    for _ in 0..50 {
        match rx.recv_timeout(std::time::Duration::from_secs(5)).unwrap() {
            RunEvent::Finished {
                cancelled,
                processed,
                ..
            } => return (cancelled, processed, logs),
            RunEvent::Log(line) => logs.push(line),
            _ => {}
        }
    }
    panic!("Finished event not observed; logs: {logs:?}");
}

#[test]
fn empty_input_finishes_without_model_contact() {
    let dir = tempfile::tempdir().unwrap();
    let (db, input) = seeded(&dir);
    let (rx, handle) = spawn(params(&db, &input), RunControl::new());
    let (cancelled, processed, _) = wait_finished(&rx);
    assert!(!cancelled);
    assert_eq!(processed, 0);
    handle.join().ok();
}

#[test]
fn cancel_before_spawn_yields_cancelled_finish() {
    let dir = tempfile::tempdir().unwrap();
    let (db, input) = seeded(&dir);
    let control = RunControl::new();
    control.request_cancel();
    let (rx, handle) = spawn(params(&db, &input), control);
    let (cancelled, _, _) = wait_finished(&rx);
    assert!(cancelled);
    handle.join().ok();
}

#[test]
fn force_and_retry_errors_are_rejected() {
    let dir = tempfile::tempdir().unwrap();
    let (db, input) = seeded(&dir);
    let mut retry_params = params(&db, &input);
    retry_params.force = true;
    retry_params.retry_errors = true;
    let (rx, handle) = spawn(retry_params, RunControl::new());
    let mut message = String::new();
    for _ in 0..10 {
        match rx.recv_timeout(std::time::Duration::from_secs(5)).unwrap() {
            RunEvent::Failed(text) => {
                message = text;
                break;
            }
            _ => {}
        }
    }
    assert_eq!(message, "--force and --retry-errors cannot be combined.");
    handle.join().ok();
}

#[test]
fn retry_errors_without_failures_logs_and_finishes_empty() {
    let dir = tempfile::tempdir().unwrap();
    let (db, input) = seeded(&dir);
    let mut retry_params = params(&db, &input);
    retry_params.retry_errors = true;
    let (rx, handle) = spawn(retry_params, RunControl::new());
    let (cancelled, processed, logs) = wait_finished(&rx);
    assert!(!cancelled);
    assert_eq!(processed, 0);
    assert!(
        logs.iter()
            .any(|l| l.contains("No failed images to retry.")),
        "logs: {logs:?}"
    );
    handle.join().ok();
}

#[test]
fn pause_blocks_completion_and_cancel_lifts_it() {
    let dir = tempfile::tempdir().unwrap();
    let (db, input) = seeded(&dir);
    let control = RunControl::new();
    control
        .paused
        .store(true, std::sync::atomic::Ordering::Relaxed);
    let (rx, handle) = spawn(params(&db, &input), control.clone());

    // While paused the run must not finish: it blocks at the phase
    // checkpoint after planning (plan/started events may already be out).
    std::thread::sleep(std::time::Duration::from_millis(400));
    loop {
        match rx.try_recv() {
            Err(mpsc::TryRecvError::Empty) => break,
            Err(mpsc::TryRecvError::Disconnected) => panic!("runner died while paused"),
            Ok(RunEvent::Finished { .. }) | Ok(RunEvent::Failed(_)) => {
                panic!("paused run must not complete")
            }
            Ok(_) => continue,
        }
    }
    control.request_cancel();

    let (cancelled, _, _) = wait_finished(&rx);
    assert!(cancelled, "cancel must lift pause and finish the run");
    handle.join().ok();
}
