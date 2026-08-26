//! GUI worker: a dedicated thread hosting the Tokio runtime. UI callbacks
//! enqueue typed requests over an mpsc channel; results return to the Slint
//! event loop via `invoke_from_event_loop`. The worker never touches widget
//! types — responses are plain data, so request handling is testable
//! headlessly.

use std::path::PathBuf;
use std::sync::mpsc;

use forza_app::{ImageInventoryFilter, ImageInventoryService};

/// Requests the UI can make.
#[derive(Debug, Clone)]
pub enum Request {
    RefreshInventory { filter: ImageInventoryFilter },
}

/// Typed response delivered back to the UI thread.
#[derive(Debug, Clone)]
pub enum Response {
    Inventory {
        result: Result<Vec<forza_app::ImageInventoryEntry>, String>,
        filter_label: String,
    },
}

/// Pure handler (no channels) so tests can exercise it headlessly.
pub fn handle_request(service: &ImageInventoryService, request: &Request) -> Response {
    match request {
        Request::RefreshInventory { filter } => Response::Inventory {
            result: service.list(filter).map_err(|e| e.to_string()),
            filter_label: filter
                .processing_status
                .clone()
                .unwrap_or_else(|| "all".to_string()),
        },
    }
}

/// Spawn the long-lived worker thread running a current-thread Tokio runtime.
/// `on_response` runs on the worker thread and must marshal results onto the
/// UI loop itself.
pub fn spawn_thread<F>(
    rx: mpsc::Receiver<Request>,
    database_file: PathBuf,
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
            let service = ImageInventoryService::new(database_file);
            runtime.block_on(async move {
                while let Ok(request) = rx.recv() {
                    // rusqlite is synchronous; queries here are fast reads.
                    // Move to spawn_blocking when heavier work arrives.
                    let response = handle_request(&service, &request);
                    on_response(response);
                }
            });
        })
        .expect("worker thread")
}
