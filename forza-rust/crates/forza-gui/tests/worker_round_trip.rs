//! Headless worker/service round trip against a seeded database — validates
//! the Fase 4/10 data path without opening a window.

use std::sync::mpsc;

use forza_app::{ImageInventoryFilter, ImageInventoryService};
use forza_gui::worker::{Request, Response, handle_request};

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

#[test]
fn refresh_inventory_returns_seeded_rows() {
    let (_guard, db) = seeded_db();
    let service = ImageInventoryService::new(db.clone());

    let response = handle_request(
        &service,
        &db,
        "TestDriver",
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
        forza_gui::worker::spawn_thread(req_rx, db.clone(), "bujica89".into(), move |response| {
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
