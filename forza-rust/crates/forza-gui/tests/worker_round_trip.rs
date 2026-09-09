//! Headless worker/service round trip against a seeded database — validates
//! the Fase 4/10 data path without opening a window.

use std::sync::mpsc;

use forza_app::{ImageInventoryFilter, ImageInventoryService};
use forza_gui::worker::{Request, Response, WorkerContext, handle_request};

fn seeded_db() -> (tempfile::TempDir, std::path::PathBuf) {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("gui-slice.sqlite3");
    forza_db::upgrade(&path).unwrap();
    {
        let mut conn = forza_db::open_connection(&path).unwrap();
        forza_db::test_support::seed_demo_database(&mut conn).unwrap();
    }
    (dir, path)
}

fn context(db: &std::path::Path, gamertag: &str) -> WorkerContext {
    // Config path guaranteed absent (unique temp name, never created):
    // exercises the missing-file → defaults path on every platform.
    // `Z:/...` was a Windows-only assumption (a valid relative path on Linux).
    let missing_ini =
        std::env::temp_dir().join(format!("forza-gui-test-missing-{}.ini", std::process::id()));
    let _ = std::fs::remove_file(&missing_ini);
    let cfg = forza_config::AppConfig {
        gamertag: gamertag.to_string(),
        ..forza_config::load_config(&missing_ini, false).unwrap().0
    };
    WorkerContext::new(db.to_path_buf(), missing_ini, cfg)
}

#[test]
fn refresh_inventory_returns_seeded_rows() {
    let (_guard, db) = seeded_db();
    let service = ImageInventoryService::new(db.clone());
    let ctx = context(&db, "TestDriver");

    let response = handle_request(
        &ctx,
        &service,
        &Request::RefreshInventory {
            filter: ImageInventoryFilter::default(),
        },
    );

    match response {
        Response::Inventory {
            result,
            filter_label,
            options,
        } => {
            assert_eq!(filter_label, "all");
            let rows = result.unwrap();
            assert_eq!(rows.len(), 2);
            assert!(rows.iter().all(|r| r.processing_status == "processed_ok"));
            let options = options.unwrap();
            assert_eq!(options.tracks, vec!["Fuji Speedway"]);
            assert_eq!(options.runs, vec!["20260101_000000_seedrun"]);
        }
        _ => panic!("expected inventory response"),
    }
}

#[test]
fn best_laps_round_trip_returns_seeded_rows() {
    let (_guard, db) = seeded_db();
    {
        let conn = forza_db::open_connection(&db).unwrap();
        conn.execute("UPDATE lap_records SET is_best_lap = 1", [])
            .unwrap();
    }
    let service = ImageInventoryService::new(db.clone());
    let ctx = context(&db, "Player One");

    let response = handle_request(&ctx, &service, &Request::ListBestLaps);
    match response {
        Response::BestLaps(result) => {
            let rows = result.unwrap();
            assert_eq!(rows.len(), 2);
            assert!(rows.iter().any(|row| row.mine));
            assert!(rows.iter().any(|row| !row.mine));
            // Screenshot-sourced laps must carry their origin image id so the
            // GUI "Image details" button can resolve it (regression: this used
            // to arrive empty and the button stayed permanently disabled).
            let image_id = rows
                .iter()
                .find_map(|row| row.image_file_id.clone())
                .expect("seeded screenshot lap must expose its image id");
            match handle_request(
                &ctx,
                &service,
                &Request::LoadImageDetail {
                    image_id: image_id.clone(),
                },
            ) {
                Response::ImageDetail(result) => {
                    let data = result.unwrap().expect("best-lap image id must resolve");
                    assert_eq!(data.meta.id, image_id);
                }
                _ => panic!("expected image-detail response"),
            }
        }
        _ => panic!("expected best-laps response"),
    }
}

#[test]
fn image_detail_round_trip_lists_seeded_content() {
    let (_guard, db) = seeded_db();
    let service = ImageInventoryService::new(db.clone());
    let ctx = context(&db, "TestDriver");

    let response = handle_request(
        &ctx,
        &service,
        &Request::LoadImageDetail {
            image_id: "img-a".into(),
        },
    );

    match response {
        Response::ImageDetail(result) => {
            let data = result.unwrap().expect("seeded image must resolve");
            assert_eq!(data.meta.id, "img-a");
            assert_eq!(data.meta.processing_status, "processed_ok");
            assert_eq!(data.laps.len(), 1);
            assert_eq!(data.laps[0].driver, "Player One");
            assert_eq!(data.results.len(), 1);
            assert_eq!(data.results[0].status, "ok");
            assert_eq!(data.attempts.len(), 1);
            assert!(data.attempts[0].accepted);
        }
        _ => panic!("expected image detail response"),
    }

    let missing = handle_request(
        &ctx,
        &service,
        &Request::LoadImageDetail {
            image_id: "nope".into(),
        },
    );
    match missing {
        Response::ImageDetail(result) => assert!(result.unwrap().is_none()),
        _ => panic!("expected image detail response"),
    }
}

#[test]
fn settings_load_preview_save_round_trip() {
    let dir = tempfile::tempdir().unwrap();
    let ini = dir.path().join("forza_config.ini");
    std::fs::write(
        &ini,
        "[paths]\ninput_dir = data/input\npdf_file = output/reports/x.pdf\nlog_file = output/logs/x.log\ndatabase_file = data/forza.sqlite3\n\n[user]\ngamertag = Player\n\n[llm]\nworkers = 1\n\n[lmstudio]\ntemperature = 0.0\n\n[prompt]\nactive = user_header_shaped_v1\n",
    )
    .unwrap();
    let db = dir.path().join("data.sqlite3");
    forza_db::upgrade(&db).unwrap();

    let cfg = forza_config::load_config(&ini, false).unwrap().0;
    let ctx = WorkerContext::new(db, ini.clone(), cfg);
    let service = ImageInventoryService::new(dir.path().join("data.sqlite3"));

    // Preview marks the edited row pending and keeps validation green.
    let mut changes = std::collections::BTreeMap::new();
    changes.insert("user.gamertag".to_string(), "Bujica89".to_string());
    match handle_request(
        &ctx,
        &service,
        &Request::PreviewSettings {
            changes: changes.clone(),
            seq: 7,
        },
    ) {
        Response::Settings(Ok(outcome)) => {
            assert_eq!(outcome.seq, 7);
            assert!(outcome.snapshot.dirty);
            assert!(outcome.snapshot.validation_ok);
            let row = outcome
                .snapshot
                .rows
                .iter()
                .find(|r| r.key == "user.gamertag")
                .unwrap();
            assert_eq!(row.value, "Bujica89");
            assert_eq!(row.status, "pending");
        }
        other => panic!("expected settings outcome, got {other:?}"),
    }

    // Save persists, recomputes the frontier (gamertag changed) and clears.
    match handle_request(&ctx, &service, &Request::SaveSettings { changes }) {
        Response::Settings(Ok(outcome)) => {
            assert!(outcome.ok);
            assert!(
                outcome.gamertag_recomputed,
                "gamertag change must recompute"
            );
            assert!(outcome.message.contains("Backup:"));
            assert!(!outcome.snapshot.dirty);
            assert_eq!(outcome.config.gamertag, "Bujica89");
            assert_eq!(ctx.gamertag(), "Bujica89");
        }
        other => panic!("expected settings outcome, got {other:?}"),
    }
    let persisted = std::fs::read_to_string(&ini).unwrap();
    assert!(persisted.contains("gamertag = Bujica89"));
    assert!(
        std::fs::read_dir(dir.path())
            .unwrap()
            .filter_map(Result::ok)
            .any(|e| e.file_name().to_string_lossy().ends_with(".bak"))
    );

    // Invalid save keeps the file untouched and surfaces the failure.
    let mut bad = std::collections::BTreeMap::new();
    bad.insert("image.encode_quality".to_string(), "999".to_string());
    match handle_request(&ctx, &service, &Request::SaveSettings { changes: bad }) {
        Response::Settings(Ok(outcome)) => {
            assert!(!outcome.ok);
            assert!(outcome.message.contains("encode_quality"));
        }
        other => panic!("expected settings outcome, got {other:?}"),
    }
}

#[test]
fn reviews_and_bestlaps_round_trip_through_worker_thread() {
    let (_guard, db) = seeded_db();

    // Job threads run each request concurrently, so responses arrive in
    // nondeterministic order AND ListBestLaps may overtake RunRebuild (then
    // the seeded rows still have is_best_lap=0 and the list is correctly
    // empty). Sequence in two phases: rebuild first, then read.
    let (req_tx, req_rx) = mpsc::channel::<Request>();
    let (res_tx, res_rx) = mpsc::channel();
    // Gamertag matches a seeded driver: the frontier needs a player baseline
    // (groups without one are skipped by design), otherwise Rebuild marks
    // nothing and ListBestLaps is legitimately empty.
    let handle =
        forza_gui::worker::spawn_thread(req_rx, context(&db, "Player One"), move |response| {
            res_tx.send(response).unwrap();
        });

    req_tx
        .send(Request::ListReviews {
            filter: forza_app::ReviewQueueFilter {
                bucket: "open".into(),
                ..Default::default()
            },
        })
        .unwrap();
    req_tx.send(Request::RunRebuild).unwrap();
    let mut saw_reviews = false;
    let mut saw_rebuild = false;
    for _ in 0..2 {
        match res_rx
            .recv_timeout(std::time::Duration::from_secs(10))
            .unwrap()
        {
            Response::Reviews { result, .. } => {
                let rows = result.unwrap();
                assert!(!rows.is_empty(), "seeded review case must be listed");
                saw_reviews = true;
            }
            Response::Rebuild(result) => {
                assert!(result.is_ok());
                saw_rebuild = true;
            }
            other => panic!("unexpected phase-1 response: {other:?}"),
        }
    }
    assert!(saw_reviews && saw_rebuild);

    req_tx.send(Request::ListBestLaps).unwrap();
    req_tx.send(Request::RunDoctor).unwrap();
    drop(req_tx);
    let mut saw_best_laps = false;
    let mut saw_doctor_ok = false;
    for _ in 0..2 {
        match res_rx
            .recv_timeout(std::time::Duration::from_secs(10))
            .unwrap()
        {
            Response::BestLaps(result) => {
                let rows = result.unwrap();
                // Seeded graph: Player One (92.5s) + Rival Driver (91.9s) on
                // Fuji Speedway, one best row per driver identity.
                assert_eq!(rows.len(), 2, "seeded best laps: {rows:?}");
                assert!(rows.iter().all(|r| r.track == "Fuji Speedway"));
                assert!(rows.iter().all(|r| r.best_lap_ms > 0));
                let mut drivers: Vec<&str> = rows.iter().map(|r| r.driver.as_str()).collect();
                drivers.sort_unstable();
                assert_eq!(drivers, vec!["Player One", "Rival Driver"]);
                saw_best_laps = true;
            }
            Response::Doctor(result) => {
                assert!(result.unwrap().ok);
                saw_doctor_ok = true;
            }
            other => panic!("unexpected phase-2 response: {other:?}"),
        }
    }
    assert!(saw_best_laps && saw_doctor_ok);
    handle.join().ok();
}

#[test]
fn delete_duplicate_removes_inputs_and_recomputes_counters() {
    let dir = tempfile::tempdir().unwrap();
    let db = dir.path().join("del.sqlite3");
    forza_db::upgrade(&db).unwrap();
    let conn = forza_db::open_connection(&db).unwrap();
    // Two files on disk inside the input dir (delete refuses outside roots).
    for name in ["canon.png", "dup.png"] {
        std::fs::write(dir.path().join(name), "x").unwrap();
    }
    conn.execute_batch(
        "INSERT INTO extraction_runs (id, status, mode, model, total_inputs, duplicate_count, created_at)
         VALUES ('run-del', 'completed', 'normal', 'm', 2, 1, datetime('now'));
         INSERT INTO image_files
            (id, file_hash, current_name, current_path, duplicate_of_image_file_id,
             file_status, first_seen_at, created_at, updated_at)
         VALUES ('img-canon', 'hash-1', 'canon.png', 'CANON_PATH', NULL, 'available',
                 datetime('now'), datetime('now'), datetime('now')),
                ('img-dup', 'hash-1', 'dup.png', 'DUP_PATH', 'img-canon', 'available',
                 datetime('now'), datetime('now'), datetime('now'));
         INSERT INTO run_inputs (id, run_id, image_file_id, input_order, input_path,
                                 decision, file_hash, duplicate_kind, duplicate_of_hash,
                                 duplicate_of_input_id, created_at)
         VALUES (1, 'run-del', 'img-canon', 0, 'canon.png', 'process',
                 'hash-1', NULL, NULL, NULL, datetime('now')),
                (2, 'run-del', 'img-dup', 1, 'dup.png', 'duplicate',
                 'hash-1', 'batch', 'hash-1', 1, datetime('now'));",
    )
    .unwrap();
    // Fix the placeholder paths to the real temp files.
    for (id, name) in [("img-canon", "canon.png"), ("img-dup", "dup.png")] {
        let full = dir.path().join(name).to_string_lossy().to_string();
        conn.execute(
            "UPDATE image_files SET current_path = ?2 WHERE id = ?1",
            rusqlite::params![id, full],
        )
        .unwrap();
    }

    let missing_ini =
        std::env::temp_dir().join(format!("forza-gui-test-del-{}.ini", std::process::id()));
    let _ = std::fs::remove_file(&missing_ini);
    let mut cfg = forza_config::load_config(&missing_ini, false).unwrap().0;
    cfg.input_dir = dir.path().to_path_buf();
    cfg.gamertag = "Player".to_string();
    let ctx = WorkerContext::new(db.clone(), missing_ini, cfg);
    let service = ImageInventoryService::new(db.clone());

    match handle_request(
        &ctx,
        &service,
        &Request::DeleteImages {
            image_ids: vec!["img-dup".to_string()],
        },
    ) {
        Response::DeleteDone(result) => {
            let (deleted, refused, sample) = result.unwrap();
            assert_eq!((deleted, refused), (1, 0), "sample: {sample}");
        }
        other => panic!("expected delete response, got {other:?}"),
    }

    // Row, file, and run inputs gone; counters recomputed like Python.
    assert!(!dir.path().join("dup.png").exists());
    assert!(dir.path().join("canon.png").exists());
    let remaining: i64 = conn
        .query_row("SELECT COUNT(*) FROM image_files", [], |r| r.get(0))
        .unwrap();
    assert_eq!(remaining, 1);
    let inputs: i64 = conn
        .query_row("SELECT COUNT(*) FROM run_inputs", [], |r| r.get(0))
        .unwrap();
    assert_eq!(inputs, 1);
    let (total, dup): (i64, i64) = conn
        .query_row(
            "SELECT total_inputs, duplicate_count FROM extraction_runs WHERE id = 'run-del'",
            [],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .unwrap();
    assert_eq!((total, dup), (1, 0));
}
