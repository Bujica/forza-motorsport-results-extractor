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

use rusqlite::OptionalExtension;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::sync::mpsc;

use forza_app::{
    ImageDebugFilter, ImageInventoryFilter, ImageInventoryService, ReviewCaseEntry,
    ReviewQueueFilter, decide_case, ignore_case, list_debug_cases, list_review_cases,
    load_debug_detail, load_debug_detail_by_result, load_image_detail, rebuild, reopen_case,
    settings_snapshot,
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

    pub fn input_dir(&self) -> PathBuf {
        self.cfg
            .lock()
            .map(|cfg| cfg.input_dir.clone())
            .unwrap_or_default()
    }
}

/// Requests the UI can make.
#[derive(Debug, Clone)]
pub enum Request {
    RefreshInventory {
        filter: ImageInventoryFilter,
    },
    SyncInputFolder {
        filter: ImageInventoryFilter,
    },
    ListReviews {
        filter: ReviewQueueFilter,
    },
    ReopenCase {
        case_number: i64,
    },
    /// Resolve the on-disk path of the linked image (UI loads the preview).
    LoadPreview {
        image_file_id: String,
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
    RunFullDoctor,
    RunRebuild,
    /// Dry-run planning through the worker (live runs use the dedicated
    /// extraction runner thread instead).
    RunDryRun {
        input_dir: String,
    },
    LoadImageDetail {
        image_id: String,
    },
    /// Dry-run rename plan for the confirmation dialog (no filesystem or DB
    /// writes); `RenameImages` below executes it.
    PreviewRename {
        image_ids: Vec<String>,
    },
    RenameImages {
        image_ids: Vec<String>,
    },
    /// Copy the selected images to a destination folder using their
    /// semantic names (falling back to the current name).
    ExportImages {
        image_ids: Vec<String>,
        dest_dir: String,
    },
    /// Re-check on-disk existence for the selected images and refresh
    /// their file_status.
    RescanImages {
        image_ids: Vec<String>,
    },
    /// Delete the selected images' files and database rows. Rows with
    /// extraction evidence are refused (FK RESTRICT) and reported.
    DeleteImages {
        image_ids: Vec<String>,
    },
    LoadSettings,
    /// Validate pending edits without saving (status bar shows the verdict).
    /// `seq` is echoed back in the outcome so the UI can drop stale
    /// responses when edits outrun the worker threads.
    PreviewSettings {
        changes: BTreeMap<String, String>,
        seq: u64,
    },
    SaveSettings {
        changes: BTreeMap<String, String>,
    },
    // ── Image Debug ────────────────────────────────────────────────────
    ListImageDebugCases {
        filter: ImageDebugFilter,
    },
    LoadImageDebugDetail {
        image_file_id: String,
        selected_result_id: Option<String>,
    },
    LoadImageDebugByResult {
        extraction_result_id: String,
    },
    // ── Logs ─────────────────────────────────────────────────────────
    LoadLogs,
    ClearLogs {
        which: String,
    },
    OpenLogFolder,
    // ── Overview ─────────────────────────────────────────────────────
    RefreshOverview,
    // ── Best Laps export/import ────────────────────────────────────────
    ImportExternalRecords {
        path: String,
    },
}

/// Dynamic combo options for the review filter bar.
#[derive(Debug, Clone, Default)]
pub struct ReviewOptions {
    pub reasons: Vec<String>,
    pub outcomes: Vec<String>,
    pub runs: Vec<String>,
}

fn review_options(conn: &rusqlite::Connection) -> Result<ReviewOptions, String> {
    let distinct = |column: &str| -> Result<Vec<String>, String> {
        let sql = format!(
            "SELECT DISTINCT COALESCE({column}, '') FROM review_cases
             WHERE COALESCE({column}, '') <> '' ORDER BY LOWER({column})"
        );
        let mut stmt = conn.prepare(&sql).map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map([], |row| row.get::<_, String>(0))
            .map_err(|e| e.to_string())?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|e| e.to_string())?;
        Ok(rows)
    };
    let runs = {
        let mut stmt = conn
            .prepare(
                "SELECT DISTINCT run_id FROM review_cases
                 WHERE run_id IS NOT NULL ORDER BY run_id DESC",
            )
            .map_err(|e| e.to_string())?;
        stmt.query_map([], |row| row.get::<_, String>(0))
            .map_err(|e| e.to_string())?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|e| e.to_string())?
    };
    // Python hardcodes the outcome vocabulary before DB values so the filter
    // is usable on an empty queue; DB-only values append after.
    let mut outcomes = vec![
        "pending".to_string(),
        "confirmed".to_string(),
        "model_error".to_string(),
        "ignored".to_string(),
    ];
    for value in distinct("outcome")? {
        if !outcomes.contains(&value) {
            outcomes.push(value);
        }
    }
    Ok(ReviewOptions {
        reasons: distinct("reason")?,
        outcomes,
        runs,
    })
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
    /// Echo of `Request::PreviewSettings.seq` (0 for load/save): lets the UI
    /// ignore an older preview that arrives after a newer one.
    pub seq: u64,
}

/// Typed response delivered back to the UI thread.
#[derive(Debug, Clone)]
pub enum Response {
    Inventory {
        result: Result<Vec<forza_app::ImageInventoryEntry>, String>,
        options: Result<forza_app::ImageInventoryOptions, String>,
        filter_label: String,
    },
    Reviews {
        result: Result<Vec<ReviewCaseEntry>, String>,
        options: ReviewOptions,
        filter: ReviewQueueFilter,
    },
    CaseDecided(Result<(), String>),
    BestLaps(Result<Vec<forza_app::BestLapRow>, String>),
    Doctor(Result<forza_app::DoctorSummary, String>),
    Rebuild(Result<forza_app::RebuildOutcome, String>),
    RunDryRunDone(String),
    ImageDetail(Result<Option<forza_app::ImageDetailData>, String>),
    RenamePreview(Result<forza_app::RenamePreview, String>),
    RenameDone(Result<String, String>),
    /// (exported count, skipped count)
    ExportDone(Result<(usize, usize), String>),
    /// (now available, now missing)
    RescanDone(Result<(usize, usize), String>),
    /// (deleted, refused, refusal summary)
    DeleteDone(Result<(usize, usize, String), String>),
    /// (image file path, None when the case has no image)
    Preview(Result<Option<String>, String>),
    CaseReopen(Result<(), String>),
    ImageDebugCases(Result<Vec<forza_db::image_debug::ImageDebugCase>, String>),
    ImageDebugDetail(Result<Option<forza_db::image_debug::ImageDebugDetail>, String>),
    Logs(Result<(String, String), String>),
    ClearLogs(Result<String, String>),
    OpenLogFolder(Result<String, String>),
    Overview(Result<forza_app::OverviewSnapshot, String>),
    Settings(Result<SettingsOutcome, String>),
    ImportDone(Result<forza_app::services::external_import::ExternalImportResult, String>),
    /// A job thread panicked; carries a display message. The UI must reset
    /// any IN_FLIGHT flag it set (the only reset points are delivered
    /// responses) so inventory/review don't wedge behind "loading…".
    Error(String),
}

/// Pure handler (no channels) so tests can exercise it headlessly.
pub fn handle_request(
    ctx: &WorkerContext,
    service: &ImageInventoryService,
    request: &Request,
) -> Response {
    match request {
        Request::RefreshInventory { filter } => {
            let options = if filter.track.is_none() && filter.run_id.is_none() {
                service.options().map_err(|e| e.to_string())
            } else {
                Ok(forza_app::ImageInventoryOptions {
                    tracks: Vec::new(),
                    runs: Vec::new(),
                })
            };
            Response::Inventory {
                result: service.list(filter).map_err(|e| e.to_string()),
                options,
                filter_label: filter
                    .processing_status
                    .clone()
                    .unwrap_or_else(|| "all".to_string()),
            }
        }
        Request::SyncInputFolder { filter } => {
            let sync_result = service.sync_input_folder(&ctx.input_dir());
            let options = if filter.track.is_none() && filter.run_id.is_none() {
                service.options().map_err(|e| e.to_string())
            } else {
                Ok(forza_app::ImageInventoryOptions {
                    tracks: Vec::new(),
                    runs: Vec::new(),
                })
            };
            Response::Inventory {
                result: sync_result
                    .and_then(|_| service.list(filter))
                    .map_err(|e| e.to_string()),
                options,
                filter_label: filter
                    .processing_status
                    .clone()
                    .unwrap_or_else(|| "all".to_string()),
            }
        }
        Request::ListReviews { filter } => {
            let outcome = (|| -> Result<(Vec<ReviewCaseEntry>, ReviewOptions), String> {
                let conn =
                    forza_db::open_connection(&ctx.database_file).map_err(|e| e.to_string())?;
                let cases = list_review_cases(&conn, filter)?;
                let options = review_options(&conn)?;
                Ok((cases, options))
            })();
            match outcome {
                Ok((cases, options)) => Response::Reviews {
                    result: Ok(cases),
                    options,
                    filter: filter.clone(),
                },
                Err(message) => Response::Reviews {
                    result: Err(message),
                    options: ReviewOptions::default(),
                    filter: filter.clone(),
                },
            }
        }
        Request::ReopenCase { case_number } => Response::CaseReopen((|| -> Result<(), String> {
            let conn = forza_db::open_connection(&ctx.database_file).map_err(|e| e.to_string())?;
            reopen_case(&conn, *case_number)?;
            // A reopened case needs its active system flag back.
            forza_db::repositories::sync_review_flags(&conn).map_err(|e| e.to_string())?;
            Ok(())
        })()),
        Request::LoadPreview { image_file_id } => {
            let result = (|| -> Result<Option<String>, String> {
                let conn =
                    forza_db::open_connection(&ctx.database_file).map_err(|e| e.to_string())?;
                conn.query_row(
                    "SELECT current_path FROM image_files WHERE id = ?1",
                    [image_file_id],
                    |r| r.get(0),
                )
                .optional()
                .map_err(|e| e.to_string())
            })();
            Response::Preview(result)
        }
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
            ignore_case(&conn, *case_number)?;
            // An ignored case must not keep an active system flag behind
            // (stale-flag doctor failure until the next run/rebuild).
            forza_db::repositories::sync_review_flags(&conn).map_err(|e| e.to_string())?;
            Ok(())
        })()),
        Request::ListBestLaps => Response::BestLaps((|| {
            let gamertag = ctx.gamertag();
            let conn = forza_db::open_connection(&ctx.database_file).map_err(|e| e.to_string())?;
            forza_app::list_best_laps(&conn, &gamertag.to_lowercase())
        })()),
        Request::RunDoctor => Response::Doctor(
            forza_db::doctor::doctor_on_path(&ctx.database_file)
                .map(forza_app::DoctorSummary::from_report)
                .map_err(|e| e.to_string()),
        ),
        Request::RunFullDoctor => Response::Doctor(
            forza_app::run_full_doctor_on_path(&ctx.database_file).map_err(|e| e.to_string()),
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
        Request::PreviewRename { image_ids } => Response::RenamePreview((|| {
            let conn = forza_db::open_connection(&ctx.database_file).map_err(|e| e.to_string())?;
            forza_app::preview_rename(&conn, image_ids)
        })()),
        Request::RenameImages { image_ids } => Response::RenameDone(rename_images(ctx, image_ids)),
        Request::ExportImages {
            image_ids,
            dest_dir,
        } => Response::ExportDone(export_images(ctx, image_ids, dest_dir)),
        Request::RescanImages { image_ids } => Response::RescanDone(rescan_images(ctx, image_ids)),
        Request::DeleteImages { image_ids } => Response::DeleteDone(delete_images(ctx, image_ids)),
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
                    seq: 0,
                })
            })();
            Response::Settings(outcome)
        }
        Request::PreviewSettings { changes, seq } => {
            let seq = *seq;
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
                        seq,
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
                            seq: 0,
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
                            seq: 0,
                        })
                    }
                }
            })();
            Response::Settings(outcome)
        }
        Request::ListImageDebugCases { filter } => Response::ImageDebugCases((|| {
            let conn = forza_db::open_connection(&ctx.database_file).map_err(|e| e.to_string())?;
            list_debug_cases(&conn, filter)
        })()),
        Request::LoadImageDebugDetail {
            image_file_id,
            selected_result_id,
        } => Response::ImageDebugDetail((|| {
            let conn = forza_db::open_connection(&ctx.database_file).map_err(|e| e.to_string())?;
            load_debug_detail(&conn, image_file_id, selected_result_id.as_deref())
        })()),
        Request::LoadImageDebugByResult {
            extraction_result_id,
        } => Response::ImageDebugDetail((|| {
            let conn = forza_db::open_connection(&ctx.database_file).map_err(|e| e.to_string())?;
            load_debug_detail_by_result(&conn, extraction_result_id)
        })()),
        Request::LoadLogs => Response::Logs((|| {
            let cfg = ctx.cfg.lock().map_err(|e| e.to_string())?.clone();
            let app_log = read_log_file(&cfg.log_file);
            // An absent errors file means "no errors recorded", not a
            // problem: say so instead of a confusing not-found path.
            let errors_path = errors_log_path(&cfg.log_file);
            let error_log = if errors_path.exists() {
                read_log_file(&errors_path)
            } else {
                "No errors recorded yet.".to_string()
            };
            Ok((app_log, error_log))
        })()),
        Request::ClearLogs { which } => Response::ClearLogs((|| {
            let cfg = ctx.cfg.lock().map_err(|e| e.to_string())?.clone();
            let target = if which == "errors" {
                errors_log_path(&cfg.log_file)
            } else {
                cfg.log_file.clone()
            };
            // Truncate file (create parent if needed)
            if let Some(parent) = target.parent() {
                std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
            }
            std::fs::write(&target, "").map_err(|e| e.to_string())?;
            Ok(format!("cleared {}", target.display()))
        })()),
        Request::OpenLogFolder => Response::OpenLogFolder((|| {
            let cfg = ctx.cfg.lock().map_err(|e| e.to_string())?.clone();
            let folder = cfg
                .log_file
                .parent()
                .unwrap_or_else(|| Path::new("."))
                .to_path_buf();
            // The folder may not exist yet (fresh install, no run logged):
            // create it so the OS dialog never reports "cannot find".
            std::fs::create_dir_all(&folder).map_err(|e| e.to_string())?;
            // Open Explorer directly instead of the generic opener: on a
            // directory that was just created this avoids a misleading
            // "Windows cannot find" shell dialog from opener backends.
            #[cfg(windows)]
            {
                std::process::Command::new("explorer")
                    .arg(&folder)
                    .spawn()
                    .map_err(|e| {
                        format!("could not launch explorer for {}: {e}", folder.display())
                    })?;
            }
            #[cfg(not(windows))]
            {
                opener::open(&folder).map_err(|e| e.to_string())?;
            }
            Ok(format!("opened {}", folder.display()))
        })()),
        Request::RefreshOverview => Response::Overview((|| {
            let cfg = ctx.cfg.lock().map_err(|e| e.to_string())?.clone();
            let conn = forza_db::open_connection(&ctx.database_file).map_err(|e| e.to_string())?;
            Ok(forza_app::build_overview_snapshot(&conn, &cfg))
        })()),
        Request::ImportExternalRecords { path } => Response::ImportDone((|| {
            let conn = forza_db::open_connection(&ctx.database_file).map_err(|e| e.to_string())?;
            forza_app::services::external_import::import_to_db(&conn, Path::new(path))
        })()),
    }
}

fn rename_images(ctx: &WorkerContext, image_ids: &[String]) -> Result<String, String> {
    let conn = forza_db::open_connection(&ctx.database_file).map_err(|e| e.to_string())?;
    let outcomes = forza_app::rename_files(&conn, image_ids, false)?;
    let changed = outcomes.iter().filter(|o| o.renamed).count();
    let errors: Vec<String> = outcomes
        .iter()
        .filter_map(|o| {
            o.error
                .as_ref()
                .map(|e| format!("{}: {e}", o.plan.image_file_id))
        })
        .collect();
    let skipped = outcomes.len() - changed - errors.len();
    if errors.is_empty() {
        Ok(format!("renamed {changed}; unchanged/missing {skipped}"))
    } else {
        Ok(format!(
            "renamed {changed}; skipped {skipped}; errors: {}",
            errors.join(" | ")
        ))
    }
}

/// Copy selected images to the destination folder using semantic names
/// when present, falling back to the current file name.
fn export_images(
    ctx: &WorkerContext,
    image_ids: &[String],
    dest_dir: &str,
) -> Result<(usize, usize), String> {
    std::fs::create_dir_all(dest_dir).map_err(|e| format!("create destination: {e}"))?;
    let conn = forza_db::open_connection(&ctx.database_file).map_err(|e| e.to_string())?;
    let mut exported = 0usize;
    let mut skipped = 0usize;
    for id in image_ids {
        let row = conn
            .query_row(
                "SELECT COALESCE(NULLIF(semantic_name, ''), current_name), current_path
                 FROM image_files WHERE id = ?1",
                [id],
                |r| Ok((r.get::<_, String>(0)?, r.get::<_, Option<String>>(1)?)),
            )
            .optional()
            .map_err(|e| e.to_string())?;
        let Some((name, Some(path))) = row else {
            skipped += 1;
            continue;
        };
        let Ok(bytes) = std::fs::read(&path) else {
            skipped += 1;
            continue;
        };
        let safe = sanitize_export_name(&name);
        // Never silently overwrite: first writer wins, later same-name files
        // get a `-N` suffix so no export is lost without accounting.
        let mut dest = std::path::Path::new(dest_dir).join(&safe);
        let mut counter = 2u32;
        while dest.exists() {
            let suffixed = match dest.file_stem().and_then(|s| s.to_str()) {
                Some(stem) => match dest.extension().and_then(|e| e.to_str()) {
                    Some(ext) => format!("{stem}-{counter}.{ext}"),
                    None => format!("{stem}-{counter}"),
                },
                None => format!("{safe}-{counter}"),
            };
            dest = std::path::Path::new(dest_dir).join(suffixed);
            counter += 1;
        }
        if std::fs::write(&dest, bytes).is_ok() {
            exported += 1;
        } else {
            skipped += 1;
        }
    }
    Ok((exported, skipped))
}

/// File-name sanitization for exports (no path separators / reserved chars).
fn sanitize_export_name(name: &str) -> String {
    let cleaned: String = name
        .chars()
        .map(|c| match c {
            '<' | '>' | ':' | '"' | '/' | '\\' | '|' | '?' | '*' => '_',
            c if c.is_control() => '_',
            c => c,
        })
        .collect();
    let trimmed = cleaned.trim().trim_end_matches('.').to_string();
    if trimmed.is_empty() {
        "export.png".to_string()
    } else {
        trimmed
    }
}

/// Re-check on-disk existence: now-missing files get file_status='missing'
/// (+missing_at), files that reappeared go back to 'available'.
fn rescan_images(ctx: &WorkerContext, image_ids: &[String]) -> Result<(usize, usize), String> {
    let conn = forza_db::open_connection(&ctx.database_file).map_err(|e| e.to_string())?;
    let mut available = 0usize;
    let mut missing = 0usize;
    for id in image_ids {
        let path: Option<String> = conn
            .query_row(
                "SELECT current_path FROM image_files WHERE id = ?1",
                [id],
                |r| r.get(0),
            )
            .optional()
            .map_err(|e| e.to_string())?;
        let Some(path) = path else { continue };
        let exists = std::path::Path::new(&path).is_file();
        let changed = conn
            .execute(
                "UPDATE image_files SET
                    file_status = ?2,
                    missing_at = CASE WHEN ?2 = 'missing' THEN datetime('now') ELSE NULL END,
                    last_seen_at = CASE WHEN ?2 = 'available' THEN datetime('now') ELSE last_seen_at END,
                    updated_at = datetime('now')
                 WHERE id = ?1 AND file_status <> ?2",
                rusqlite::params![id, if exists { "available" } else { "missing" }],
            )
            .map_err(|e| e.to_string())?;
        if changed > 0 {
            if exists {
                available += 1;
            } else {
                missing += 1;
            }
        }
    }
    Ok((available, missing))
}

/// Delete files + database rows. Images with extraction evidence are
/// refused by FK RESTRICT — they are counted and summarized, not deleted.
fn delete_images(
    ctx: &WorkerContext,
    image_ids: &[String],
) -> Result<(usize, usize, String), String> {
    let conn = forza_db::open_connection(&ctx.database_file).map_err(|e| e.to_string())?;
    let input_dir = ctx.input_dir();
    let mut deleted = 0usize;
    let mut refused = 0usize;
    let mut refusal_sample = String::new();
    for id in image_ids {
        let row: Option<(Option<String>, String)> = conn
            .query_row(
                "SELECT current_path, current_name FROM image_files WHERE id = ?1",
                [id],
                |r| Ok((r.get::<_, Option<String>>(0)?, r.get::<_, String>(1)?)),
            )
            .optional()
            .map_err(|e| e.to_string())?;
        let Some((Some(path), name)) = row else {
            refused += 1;
            continue;
        };
        // Safety: only delete files inside the configured input folder.
        // Both sides are canonicalized (Windows `canonicalize()` yields
        // `\\?\C:\…` verbatim paths) and subfolders are allowed via
        // `starts_with` — a bare `parent == input_dir` check would refuse
        // everything and reject legitimate subfolder images.
        let allowed = (|| -> Option<bool> {
            let canon_path = std::path::Path::new(&path).canonicalize().ok()?;
            let canon_dir = std::path::Path::new(&input_dir).canonicalize().ok()?;
            // The file itself or its parent must live under the input dir.
            if canon_path.starts_with(&canon_dir) {
                return Some(true);
            }
            let parent = canon_path.parent()?;
            Some(parent.starts_with(&canon_dir))
        })()
        .unwrap_or(false);
        if !allowed {
            refused += 1;
            if refusal_sample.len() < 2000 {
                refusal_sample.push_str(&format!("{name} (outside input folder); "));
            }
            continue;
        }
        // Delete the DB row FIRST: if FK RESTRICT refuses (extraction
        // evidence exists) the file on disk must be preserved. Deleting the
        // file first would cause silent data loss with a misleading
        // "has extraction evidence" report.
        match conn.execute("DELETE FROM image_files WHERE id = ?1", [id]) {
            Ok(n) if n > 0 => {
                if let Err(e) = std::fs::remove_file(&path) {
                    // Row is gone but the file remains: report it explicitly
                    // (recoverable via rescan) instead of counting success.
                    refused += 1;
                    if refusal_sample.len() < 2000 {
                        refusal_sample.push_str(&format!("{name} (db-deleted-file-kept: {e}); "));
                    }
                    continue;
                }
                deleted += 1;
            }
            Ok(_) => {
                refused += 1;
            }
            Err(e) => {
                refused += 1;
                let reason = if e.to_string().contains("FOREIGN KEY") {
                    "has extraction evidence".to_string()
                } else {
                    e.to_string()
                };
                let reason = reason.as_str();
                if refusal_sample.len() < 2000 {
                    refusal_sample.push_str(&format!("{name}: {reason}; "));
                }
            }
        }
    }
    Ok((deleted, refused, refusal_sample))
}

/// Canonical errors-log sibling, shared with the run-log writer in
/// `forza-app` (single definition of the `<stem>_errors<suffix>` rule).
fn errors_log_path(log_file: &Path) -> PathBuf {
    forza_app::errors_log_path(log_file)
}

fn read_log_file(path: &Path) -> String {
    if !path.exists() {
        return format!("Log file not found: {}", path.display());
    }
    match std::fs::read_to_string(path) {
        Ok(content) if content.len() > 200_000 => {
            // Find the cut point BEFORE slicing: `content.len()` is bytes,
            // so slicing first panics when a multi-byte char straddles the
            // cut (this app logs "✓"/"→"). Advance to the next char boundary.
            let mut cut = content.len() - 200_000;
            while cut < content.len() && !content.is_char_boundary(cut) {
                cut += 1;
            }
            format!("… [truncated to last 200KB] …\n{}", &content[cut..])
        }
        Ok(content) => content,
        Err(e) => format!("Could not read log file: {}\n{e}", path.display()),
    }
}

/// Spawn the long-lived worker thread. Each request is handled on its own
/// short-lived thread so a heavy `RunFullDoctor` (63 checks + file I/O) does
/// not block `LoadImageDetail` / `LoadImageDebugDetail` — parity with Python's
/// per-controller QThread workers.
pub fn spawn_thread<F>(
    rx: mpsc::Receiver<Request>,
    ctx: WorkerContext,
    on_response: F,
) -> std::thread::JoinHandle<()>
where
    F: Fn(Response) + Send + 'static,
{
    use std::sync::{Arc, Mutex};
    let ctx = Arc::new(ctx);
    let service = Arc::new(ImageInventoryService::new(ctx.database_file.clone()));
    let on_response = Arc::new(Mutex::new(on_response));
    std::thread::Builder::new()
        .name("forza-gui-worker".into())
        .spawn(move || {
            while let Ok(request) = rx.recv() {
                let ctx = Arc::clone(&ctx);
                let service = Arc::clone(&service);
                let on_response = Arc::clone(&on_response);
                // Handle each request concurrently; response marshals back via
                // `slint::invoke_from_event_loop` inside `on_response`.
                std::thread::Builder::new()
                    .name("forza-gui-worker-job".into())
                    .spawn(move || {
                        // Never let a panicking job wedge the coalescing flags:
                        // the UI only resets IN_FLIGHT on a delivered response,
                        // so a silent thread death would freeze inventory/review
                        // behind "loading…" forever.
                        let response =
                            match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                                handle_request(&ctx, &service, &request)
                            })) {
                                Ok(r) => r,
                                Err(_) => Response::Error(
                                    "background job panicked; please retry".to_string(),
                                ),
                            };
                        if let Ok(f) = on_response.lock() {
                            f(response);
                        }
                    })
                    .expect("job thread");
            }
        })
        .expect("worker thread")
}
