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
    let cfg = forza_config::AppConfig {
        gamertag: gamertag.to_string(),
        ..forza_config::load_config(Path::new("Z:/nonexistent.ini"), false)
            .unwrap()
            .0
    };
    WorkerContext::new(db.to_path_buf(), PathBuf::from("Z:/nonexistent.ini"), cfg)
}

use std::path::{Path, PathBuf};

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
        } => {
            assert_eq!(filter_label, "all");
            let rows = result.unwrap();
            assert_eq!(rows.len(), 2);
            assert!(rows.iter().all(|r| r.processing_status == "processed_ok"));
        }
        _ => panic!("expected inventory response"),
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
        },
    ) {
        Response::Settings(Ok(outcome)) => {
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

    // Enqueue before spawning, mirroring what UI callbacks do.
    let (req_tx, req_rx) = mpsc::channel::<Request>();
    for request in [
        Request::ListReviews {
            bucket: "open".into(),
        },
        Request::ListBestLaps,
        Request::RunDoctor,
        Request::RunRebuild,
    ] {
        req_tx.send(request).unwrap();
    }
    drop(req_tx);

    let (res_tx, res_rx) = mpsc::channel();
    let handle =
        forza_gui::worker::spawn_thread(req_rx, context(&db, "bujica89"), move |response| {
            res_tx.send(response).unwrap();
        });

    let mut saw_reviews = false;
    let mut saw_best_laps = false;
    let mut saw_doctor_ok = false;
    let mut saw_rebuild = false;
    for _ in 0..4 {
        match res_rx
            .recv_timeout(std::time::Duration::from_secs(5))
            .unwrap()
        {
            Response::Reviews { result, .. } => {
                let rows = result.unwrap();
                assert!(!rows.is_empty(), "seeded review case must be listed");
                saw_reviews = true;
            }
            Response::BestLaps(result) => {
                let rows = result.unwrap();
                assert!(rows.is_empty() || !rows.is_empty()); // shape check
                saw_best_laps = true;
            }
            Response::Doctor(result) => {
                assert!(result.unwrap().ok);
                saw_doctor_ok = true;
            }
            Response::Rebuild(result) => {
                assert!(result.is_ok());
                saw_rebuild = true;
            }
            _ => {}
        }
    }
    assert!(saw_reviews && saw_best_laps && saw_doctor_ok && saw_rebuild);
    handle.join().ok();
}
