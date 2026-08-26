//! Headless worker/service round trip against a seeded database — validates
//! the Fase 4 data path without opening a window.

use std::sync::mpsc;

use forza_app::{ImageInventoryFilter, ImageInventoryService};
use forza_gui::worker::{Request, handle_request};

fn seeded_db() -> tempfile::TempDir {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("gui-slice.sqlite3");
    forza_db::upgrade(&path).unwrap();
    {
        let mut conn = forza_db::open_connection(&path).unwrap();
        forza_db::test_support::seed_demo_database(&mut conn).unwrap();
    }
    dir
}

#[test]
fn refresh_inventory_returns_seeded_rows() {
    let dir = seeded_db();
    let service = ImageInventoryService::new(dir.path().join("gui-slice.sqlite3"));

    let response = handle_request(
        &service,
        &Request::RefreshInventory {
            filter: ImageInventoryFilter::default(),
        },
    );

    match response {
        forza_gui::worker::Response::Inventory {
            result,
            filter_label,
        } => {
            assert_eq!(filter_label, "all");
            let rows = result.unwrap();
            assert_eq!(rows.len(), 2);
            assert!(rows.iter().all(|r| r.processing_status == "processed_ok"));
        }
    }
}

#[test]
fn filter_narrows_results_through_the_service_path() {
    let dir = seeded_db();
    let service = ImageInventoryService::new(dir.path().join("gui-slice.sqlite3"));
    let response = handle_request(
        &service,
        &Request::RefreshInventory {
            filter: ImageInventoryFilter {
                processing_status: Some("unprocessed".into()),
                ..Default::default()
            },
        },
    );
    match response {
        forza_gui::worker::Response::Inventory {
            result,
            filter_label,
        } => {
            assert_eq!(filter_label, "unprocessed");
            assert_eq!(result.unwrap().len(), 0);
        }
    }
}

#[test]
fn worker_thread_round_trip_delivers_typed_response() {
    let dir = seeded_db();

    // Enqueue the request before spawning, mirroring what a UI callback does.
    let (req_tx, req_rx) = mpsc::channel::<Request>();
    req_tx
        .send(Request::RefreshInventory {
            filter: ImageInventoryFilter::default(),
        })
        .unwrap();
    drop(req_tx);

    let (res_tx, res_rx) = mpsc::channel();
    let handle = forza_gui::worker::spawn_thread(
        req_rx,
        dir.path().join("gui-slice.sqlite3"),
        move |response| res_tx.send(response).unwrap(),
    );

    let got = res_rx
        .recv_timeout(std::time::Duration::from_secs(5))
        .unwrap();
    assert!(matches!(got, forza_gui::worker::Response::Inventory { .. }));
    handle.join().ok();
}
