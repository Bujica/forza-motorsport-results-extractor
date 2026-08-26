//! GUI worker: a dedicated thread hosting the Tokio runtime. UI callbacks
//! enqueue typed requests over an mpsc channel; results return to the Slint
//! event loop via `invoke_from_event_loop`. The worker never touches widget
//! types — responses are plain data, so request handling is testable
//! headlessly.

use std::path::PathBuf;
use std::sync::mpsc;

use forza_app::{
    ImageInventoryFilter, ImageInventoryService, ReviewCaseEntry, decide_case, ignore_case,
    list_clean_flat_entries, list_review_cases, rebuild,
};

/// Requests the UI can make.
#[derive(Debug, Clone)]
pub enum Request {
    RefreshInventory {
        filter: ImageInventoryFilter,
    },
    ListReviews {
        bucket: String,
    },
    DecideCase {
        case_number: i64,
        field: String,
        value: String,
    },
    IgnoreCase {
        case_number: i64,
    },
    ListBestLaps,
    RunDoctor,
    RunRebuild,
}

/// Typed response delivered back to the UI thread.
#[derive(Debug, Clone)]
pub enum Response {
    Inventory {
        result: Result<Vec<forza_app::ImageInventoryEntry>, String>,
        filter_label: String,
    },
    Reviews {
        result: Result<Vec<ReviewCaseEntry>, String>,
        bucket: String,
    },
    CaseDecided(Result<(), String>),
    BestLaps(Result<Vec<forza_app::BestLapEntry>, String>),
    Doctor(Result<forza_app::DoctorSummary, String>),
    Rebuild(Result<forza_app::RebuildOutcome, String>),
}

/// Pure handler (no channels) so tests can exercise it headlessly.
pub fn handle_request(
    service: &ImageInventoryService,
    database_file: &std::path::Path,
    gamertag: &str,
    request: &Request,
) -> Response {
    match request {
        Request::RefreshInventory { filter } => Response::Inventory {
            result: service.list(filter).map_err(|e| e.to_string()),
            filter_label: filter
                .processing_status
                .clone()
                .unwrap_or_else(|| "all".to_string()),
        },
        Request::ListReviews { bucket } => Response::Reviews {
            result: (|| {
                let conn = forza_db::open_connection(database_file).map_err(|e| e.to_string())?;
                list_review_cases(&conn, bucket)
            })(),
            bucket: bucket.clone(),
        },
        Request::DecideCase {
            case_number,
            field,
            value,
        } => Response::CaseDecided((|| {
            let mut conn = forza_db::open_connection(database_file).map_err(|e| e.to_string())?;
            decide_case(&mut conn, *case_number, field, value)?;
            // A correction changes lap facts: refresh derived state.
            let outcome = rebuild(&conn, gamertag)?;
            let _ = outcome;
            Ok(())
        })()),
        Request::IgnoreCase { case_number } => Response::CaseDecided((|| {
            let conn = forza_db::open_connection(database_file).map_err(|e| e.to_string())?;
            ignore_case(&conn, *case_number)
        })()),
        Request::ListBestLaps => Response::BestLaps((|| {
            let conn = forza_db::open_connection(database_file).map_err(|e| e.to_string())?;
            list_clean_flat_entries(&conn, &gamertag.to_lowercase())
        })()),
        Request::RunDoctor => Response::Doctor(
            forza_db::doctor::doctor_on_path(database_file)
                .map(forza_app::DoctorSummary::from_report)
                .map_err(|e| e.to_string()),
        ),
        Request::RunRebuild => Response::Rebuild((|| {
            let conn = forza_db::open_connection(database_file).map_err(|e| e.to_string())?;
            rebuild(&conn, gamertag)
        })()),
    }
}

/// Spawn the long-lived worker thread running a current-thread Tokio runtime.
/// `on_response` runs on the worker thread and must marshal results onto the
/// UI loop itself.
pub fn spawn_thread<F>(
    rx: mpsc::Receiver<Request>,
    database_file: PathBuf,
    gamertag: String,
    on_response: F,
) -> std::thread::JoinHandle<()>
where
    F: Fn(Response) + Send + 'static,
{
    std::thread::Builder::new()
        .name("forza-gui-worker".into())
        .spawn(move || {
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .expect("tokio runtime");
            let service = ImageInventoryService::new(database_file.clone());
            runtime.block_on(async move {
                while let Ok(request) = rx.recv() {
                    // rusqlite is synchronous; queries here are fast reads.
                    // Move to spawn_blocking when heavier work arrives.
                    let response = handle_request(&service, &database_file, &gamertag, &request);
                    on_response(response);
                }
            });
        })
        .expect("worker thread")
}
