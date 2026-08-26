//! GUI worker: a dedicated thread hosting the Tokio runtime. UI callbacks
//! enqueue typed requests over an mpsc channel; results return to the Slint
//! event loop via `invoke_from_event_loop`. The worker never touches widget
//! types — responses are plain data, so request handling is testable
//! headlessly.
//!
//! The worker owns the live [`AppConfig`] (settings saves update it in
//! place) plus the INI path, so every handler observes the current
//! configuration — the Rust counterpart of the Python `GuiConfigState`
//! live-provider rule.

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::Mutex;
use std::sync::mpsc;

use forza_app::{
    ImageInventoryFilter, ImageInventoryService, ReviewCaseEntry, decide_case, ignore_case,
    list_clean_flat_entries, list_review_cases, load_image_detail, rebuild, settings_snapshot,
};

/// Live configuration owned by the worker thread.
pub struct WorkerContext {
    pub database_file: PathBuf,
    pub config_path: PathBuf,
    pub cfg: Mutex<forza_config::AppConfig>,
}

impl WorkerContext {
    pub fn new(database_file: PathBuf, config_path: PathBuf, cfg: forza_config::AppConfig) -> Self {
        Self {
            database_file,
            config_path,
            cfg: Mutex::new(cfg),
        }
    }

    pub fn gamertag(&self) -> String {
        self.cfg
            .lock()
            .map(|cfg| cfg.gamertag.clone())
            .unwrap_or_default()
    }
}

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
    /// Dry-run planning through the worker (live runs use the dedicated
    /// extraction runner thread instead).
    RunDryRun {
        input_dir: String,
    },
    LoadImageDetail {
        image_id: String,
    },
    LoadSettings,
    /// Validate pending edits without saving (status bar shows the verdict).
    PreviewSettings {
        changes: BTreeMap<String, String>,
    },
    SaveSettings {
        changes: BTreeMap<String, String>,
    },
}

/// Outcome of a settings load/preview/save — always carries a fresh
/// snapshot plus the effective config so the UI can refresh dependent
/// state (run info line, gamertag header).
#[derive(Debug, Clone, PartialEq)]
pub struct SettingsOutcome {
    /// Whether the mutation (save) succeeded; previews are always true.
    pub ok: bool,
    pub message: String,
    pub snapshot: forza_app::SettingsSnapshot,
    pub config: forza_config::AppConfig,
    /// True when a save changed `user.gamertag` and the best-lap frontier
    /// was recomputed (configuration contract).
    pub gamertag_recomputed: bool,
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
    RunDryRunDone(String),
    ImageDetail(Result<Option<forza_app::ImageDetailData>, String>),
    Settings(Result<SettingsOutcome, String>),
}

/// Pure handler (no channels) so tests can exercise it headlessly.
pub fn handle_request(
    ctx: &WorkerContext,
    service: &ImageInventoryService,
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
                let conn =
                    forza_db::open_connection(&ctx.database_file).map_err(|e| e.to_string())?;
                list_review_cases(&conn, bucket, None)
            })(),
            bucket: bucket.clone(),
        },
        Request::DecideCase {
            case_number,
            field,
            value,
        } => Response::CaseDecided((|| {
            let gamertag = ctx.gamertag();
            let mut conn =
                forza_db::open_connection(&ctx.database_file).map_err(|e| e.to_string())?;
            decide_case(&mut conn, *case_number, field, value)?;
            // A correction changes lap facts: refresh derived state.
            let outcome = rebuild(&conn, &gamertag)?;
            let _ = outcome;
            Ok(())
        })()),
        Request::IgnoreCase { case_number } => Response::CaseDecided((|| {
            let conn = forza_db::open_connection(&ctx.database_file).map_err(|e| e.to_string())?;
            ignore_case(&conn, *case_number)
        })()),
        Request::ListBestLaps => Response::BestLaps((|| {
            let gamertag = ctx.gamertag();
            let conn = forza_db::open_connection(&ctx.database_file).map_err(|e| e.to_string())?;
            list_clean_flat_entries(&conn, &gamertag.to_lowercase())
        })()),
        Request::RunDoctor => Response::Doctor(
            forza_db::doctor::doctor_on_path(&ctx.database_file)
                .map(forza_app::DoctorSummary::from_report)
                .map_err(|e| e.to_string()),
        ),
        Request::RunRebuild => Response::Rebuild((|| {
            let gamertag = ctx.gamertag();
            let conn = forza_db::open_connection(&ctx.database_file).map_err(|e| e.to_string())?;
            rebuild(&conn, &gamertag)
        })()),
        Request::RunDryRun { input_dir } => {
            let summary = (|| -> Result<String, String> {
                let conn =
                    forza_db::open_connection(&ctx.database_file).map_err(|e| e.to_string())?;
                let known_paths =
                    forza_db::repositories::known_path_hashes(&conn).map_err(|e| e.to_string())?;
                let known =
                    forza_db::repositories::known_hashes(&conn).map_err(|e| e.to_string())?;
                let images = forza_pipeline::find_images(std::path::Path::new(input_dir));
                let plan = forza_pipeline::plan_images(&images, &known, &known_paths, false)
                    .map_err(|e| e.to_string())?;
                Ok(format!(
                    "dry-run: total={} new={} cached={} batch={} existing={} skipped={}",
                    plan.total,
                    plan.process_count(),
                    plan.duplicates
                        .iter()
                        .filter(|d| d.reason == "cached")
                        .count(),
                    plan.duplicates
                        .iter()
                        .filter(|d| d.reason == "batch")
                        .count(),
                    plan.existing_images.len(),
                    plan.skipped_images.len()
                ))
            })()
            .unwrap_or_else(|e| format!("dry-run failed: {e}"));
            Response::RunDryRunDone(summary)
        }
        Request::LoadImageDetail { image_id } => Response::ImageDetail((|| {
            let conn = forza_db::open_connection(&ctx.database_file).map_err(|e| e.to_string())?;
            load_image_detail(&conn, image_id)
        })()),
        Request::LoadSettings => {
            let outcome = (|| -> Result<SettingsOutcome, String> {
                let (cfg, _) =
                    forza_config::load_config(&ctx.config_path, false).map_err(|e| e.message)?;
                *ctx.cfg.lock().map_err(|e| e.to_string())? = cfg.clone();
                let snapshot = settings_snapshot(&cfg, &BTreeMap::new(), false, None);
                Ok(SettingsOutcome {
                    ok: true,
                    message: String::new(),
                    snapshot,
                    config: cfg,
                    gamertag_recomputed: false,
                })
            })();
            Response::Settings(outcome)
        }
        Request::PreviewSettings { changes } => {
            let current = ctx.cfg.lock().map(|c| c.clone()).map_err(|e| e.to_string());
            let outcome = match current {
                Err(e) => Err(e),
                Ok(current) => {
                    let verdict = forza_config::save::validate_changes(&ctx.config_path, changes);
                    let (validation_ok, message) = match verdict {
                        Ok(message) => (true, message),
                        Err(message) => (false, message),
                    };
                    let snapshot = settings_snapshot(
                        &current,
                        changes,
                        !changes.is_empty(),
                        Some((validation_ok, message)),
                    );
                    Ok(SettingsOutcome {
                        ok: true,
                        message: String::new(),
                        snapshot,
                        config: current,
                        gamertag_recomputed: false,
                    })
                }
            };
            Response::Settings(outcome)
        }
        Request::SaveSettings { changes } => {
            let outcome = (|| -> Result<SettingsOutcome, String> {
                match forza_config::save::save_changes(&ctx.config_path, changes) {
                    Ok(saved) => {
                        *ctx.cfg.lock().map_err(|e| e.to_string())? = saved.config.clone();
                        let gamertag_recomputed = if saved.gamertag_changed {
                            let conn = forza_db::open_connection(&ctx.database_file)
                                .map_err(|e| e.to_string())?;
                            rebuild(&conn, &saved.config.gamertag)?;
                            true
                        } else {
                            false
                        };
                        let snapshot =
                            settings_snapshot(&saved.config, &BTreeMap::new(), false, None);
                        Ok(SettingsOutcome {
                            ok: true,
                            message: saved.message,
                            snapshot,
                            config: saved.config,
                            gamertag_recomputed,
                        })
                    }
                    Err(message) => {
                        let current = ctx
                            .cfg
                            .lock()
                            .map(|c| c.clone())
                            .map_err(|e| e.to_string())?;
                        let snapshot = settings_snapshot(
                            &current,
                            changes,
                            !changes.is_empty(),
                            Some((false, message.clone())),
                        );
                        Ok(SettingsOutcome {
                            ok: false,
                            message,
                            snapshot,
                            config: current,
                            gamertag_recomputed: false,
                        })
                    }
                }
            })();
            Response::Settings(outcome)
        }
    }
}

/// Spawn the long-lived worker thread running a current-thread Tokio runtime.
/// `on_response` runs on the worker thread and must marshal results onto the
/// UI loop itself.
pub fn spawn_thread<F>(
    rx: mpsc::Receiver<Request>,
    ctx: WorkerContext,
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
            let service = ImageInventoryService::new(ctx.database_file.clone());
            runtime.block_on(async move {
                while let Ok(request) = rx.recv() {
                    // rusqlite is synchronous; queries here are fast reads.
                    // Move to spawn_blocking when heavier work arrives.
                    let response = handle_request(&ctx, &service, &request);
                    on_response(response);
                }
            });
        })
        .expect("worker thread")
}
