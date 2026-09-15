//! forza-gui: Slint front-end of the Rust line (Fase 4 slice + F10 pages).
//!
//! Threading contract (migration plan §4.9): the Tokio runtime lives on a
//! dedicated worker thread; Slint callbacks are synchronous and only enqueue
//! typed requests; results come back to the UI thread through
//! `slint::invoke_from_event_loop`. Widget-adjacent state (`Rc` models, row
//! cache) lives in UI-thread locals and is never shared across threads.

pub mod callbacks;
pub mod detail_views;
pub mod ui_persist;
pub mod ui_state;
pub mod worker;

use ui_state::{
    BESTLAP_FILTER, BESTLAP_MODEL, CONFIG_PATH, DEBUG_CASE_MODEL, DEBUG_RESULT_MODEL,
    DETAIL_ATTEMPT_MODEL, DETAIL_LAP_MODEL, DETAIL_RESULT_MODEL, DETAIL_REVIEW_MODEL, GAMERTAG,
    INVENTORY_REFRESH_IN_FLIGHT, LIST_MODEL, REVIEW_MODEL, RUN_CONFIG, RUN_LOG, SETTINGS_MODEL,
    WORKER_TX, remember_inventory_filter, run_info_line, send_request,
};

use std::path::{Path, PathBuf};
use std::rc::Rc;
use std::sync::mpsc;

use slint::{ModelRc, VecModel};

use crate::worker::{Request, WorkerContext};
use forza_app::{ImageInventoryFilter, ReviewQueueFilter};

slint::include_modules!();

/// Primary display work area in physical px (0 when unknown).
#[cfg(windows)]
fn primary_screen_px() -> (i32, i32) {
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        GetSystemMetrics, SM_CXFULLSCREEN, SM_CYFULLSCREEN,
    };
    // SAFETY: trivial side-effect-free win32 metric query; no pointers,
    // no invariants to uphold beyond a valid constant.
    (unsafe { GetSystemMetrics(SM_CXFULLSCREEN) }, unsafe {
        GetSystemMetrics(SM_CYFULLSCREEN)
    })
}

#[cfg(not(windows))]
fn primary_screen_px() -> (i32, i32) {
    (0, 0)
}

/// Python-parity first-launch size: min(92% work area width, 1600) x
/// min(88% work area height, 950). Falls back to the Window's preferred
/// size when the display metrics are unavailable or implausible.
fn first_launch_window_size(main: &MainWindow) -> (f32, f32) {
    let (sw, sh) = primary_screen_px();
    if sw < 800 || sh < 600 {
        return (1400.0, 800.0);
    }
    let sf = main.window().scale_factor().max(0.5);
    let (lw, lh) = (sw as f32 / sf, sh as f32 / sf);
    if !(900.0..=8000.0).contains(&lw) || !(600.0..=5000.0).contains(&lh) {
        return (1400.0, 800.0);
    }
    ((lw * 0.92).min(1600.0), (lh * 0.88).min(950.0))
}

/// Clamp a restored splitter length into a sane band around `base`.
fn clamp_split(value: f32, base: f32) -> f32 {
    value.clamp(150.0, (base - 150.0).max(150.0))
}

/// Outcome of [`ensure_database`]: `None` means the user chose to quit (or a
/// recovery failure was already reported in a dialog), so startup should exit
/// gracefully instead of propagating an error nobody can see.
#[derive(Debug)]
struct DbReady {
    created: bool,
}

/// How to recover from an incompatible database (the dialog answer, kept
/// separate so the file operations stay testable without showing any UI).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RecoveryChoice {
    /// Migrate in place, preserving data (a backup is made first).
    Migrate,
    /// Back up the old file and create a fresh database.
    Recreate,
    /// Quit without touching anything.
    Quit,
}

/// What the recovery did (surfaced in the confirmation dialog).
#[derive(Debug)]
enum RecoveryDone {
    Migrated { backup: PathBuf },
    Recreated { backup: PathBuf },
}

/// Ask what to do with an incompatible database. Yes = migrate in place,
/// No = back up and recreate fresh, Cancel/closed = quit untouched.
fn ask_database_recovery(db_path: &Path, found: i64) -> RecoveryChoice {
    use forza_db::migration::SCHEMA_VERSION;
    match rfd::MessageDialog::new()
        .set_title("Incompatible database")
        .set_description(format!(
            "This database uses schema v{found}, but this build expects v{SCHEMA_VERSION}.\n\n\
             Yes — migrate in place (keeps your data; a backup is made first).\n\
             No — back up the old file and create a fresh database.\n\
             Cancel — quit without changing anything.\n\n\
             {}",
            db_path.display()
        ))
        .set_buttons(rfd::MessageButtons::YesNoCancel)
        .set_level(rfd::MessageLevel::Warning)
        .show()
    {
        rfd::MessageDialogResult::Yes => RecoveryChoice::Migrate,
        rfd::MessageDialogResult::No => RecoveryChoice::Recreate,
        _ => RecoveryChoice::Quit,
    }
}

fn show_dialog(level: rfd::MessageLevel, title: &str, body: &str) {
    rfd::MessageDialog::new()
        .set_title(title)
        .set_description(body)
        .set_level(level)
        .show();
}

/// Execute a recovery choice: backup + migrate or recreate. Pure file
/// operations, no UI — the dialog only decides the `choice`.
fn resolve_incompatible(
    db_path: &Path,
    choice: RecoveryChoice,
) -> anyhow::Result<Option<RecoveryDone>> {
    use forza_db::migration::{backup_database, migrate, sidecar_paths, upgrade};
    match choice {
        RecoveryChoice::Quit => Ok(None),
        RecoveryChoice::Migrate => {
            let backup = backup_database(db_path).map_err(|e| anyhow::anyhow!("{e}"))?;
            migrate(db_path).map_err(|e| anyhow::anyhow!("{e}"))?;
            Ok(Some(RecoveryDone::Migrated { backup }))
        }
        RecoveryChoice::Recreate => {
            let backup = backup_database(db_path).map_err(|e| anyhow::anyhow!("{e}"))?;
            std::fs::remove_file(db_path)?;
            for sidecar in sidecar_paths(db_path) {
                if sidecar.exists() {
                    std::fs::remove_file(&sidecar)?;
                }
            }
            upgrade(db_path).map_err(|e| anyhow::anyhow!("{e}"))?;
            Ok(Some(RecoveryDone::Recreated { backup }))
        }
    }
}

/// Create the database from zero when missing; on an incompatible schema ask
/// (native dialog) whether to migrate, recreate, or quit. A silent `Err`
/// here kills the process with no visible message on a console-less Windows
/// launch, so every path either recovers, informs via dialog, or quits by
/// explicit choice.
fn ensure_database(db_path: &Path) -> anyhow::Result<Option<DbReady>> {
    use forza_db::migration::{SchemaStatus, schema_status, upgrade};
    match schema_status(db_path).map_err(|e| anyhow::anyhow!("{e}"))? {
        SchemaStatus::Empty => {
            upgrade(db_path).map_err(|e| anyhow::anyhow!("{e}"))?;
            Ok(Some(DbReady { created: true }))
        }
        SchemaStatus::Current => Ok(Some(DbReady { created: false })),
        SchemaStatus::Incompatible { found } => {
            let choice = ask_database_recovery(db_path, found);
            match resolve_incompatible(db_path, choice) {
                Ok(recovered) => {
                    if recovered.is_none() {
                        // Explicit Quit: leave everything untouched.
                        return Ok(None);
                    }
                    if let Some(RecoveryDone::Migrated { ref backup })
                    | Some(RecoveryDone::Recreated { ref backup }) = recovered
                    {
                        let what = if matches!(recovered, Some(RecoveryDone::Migrated { .. })) {
                            "migrated"
                        } else {
                            "recreated"
                        };
                        let body = format!(
                            "Database {what}; the previous file was kept as a backup:\n{}",
                            backup.display()
                        );
                        eprintln!("{body}");
                        show_dialog(rfd::MessageLevel::Info, "Database ready", &body);
                    }
                    Ok(Some(DbReady { created: false }))
                }
                Err(e) => {
                    let body = format!(
                        "Database recovery failed: {e}\n\n\
                         Delete the file or run `forza maintenance db-reset --yes` \
                         to recreate it from zero."
                    );
                    eprintln!("{body}");
                    show_dialog(rfd::MessageLevel::Error, "Database recovery failed", &body);
                    Ok(None)
                }
            }
        }
    }
}

/// Launch the GUI. Blocks until the window closes.
pub fn run(config_path: &Path) -> anyhow::Result<()> {
    // First launch must be self-sufficient: a missing INI is bootstrapped
    // from the shipped example next to it (bundle layout), so a fresh
    // tester never has to hand-copy files before opening the app.
    if !config_path.exists()
        && let Some(dir) = config_path.parent()
        && !dir.as_os_str().is_empty()
    {
        let example = dir.join("forza_config.ini.example");
        if example.exists() {
            std::fs::copy(&example, config_path)?;
        }
    }
    let (mut cfg, warnings) = forza_config::load_config(config_path, false)?;
    for warning in warnings {
        eprintln!("config warning: {warning}");
    }
    forza_config::validate_config(&cfg)
        .map_err(|errors| anyhow::anyhow!("configuration invalid: {}", errors.join("; ")))?;

    // One rule everywhere (same as the CLI): relative [paths] resolve
    // against the INI folder, never against the working directory and never
    // by hunting the filesystem for some other database. What Settings
    // shows is what the app uses.
    forza_config::resolve_paths(config_path, &mut cfg);

    // Fresh installs must not greet the tester with "missing" badges: the
    // input folder and the output/database parents are created idempotently.
    // (Exports and logs still create their own parents on demand.)
    std::fs::create_dir_all(&cfg.input_dir)?;
    for file_path in [&cfg.pdf_file, &cfg.log_file, &cfg.database_file] {
        if let Some(parent) = file_path.parent()
            && !parent.as_os_str().is_empty()
        {
            std::fs::create_dir_all(parent)?;
        }
    }

    let db_path: PathBuf = cfg.database_file.clone();
    // Missing/empty databases are created from zero with no prompt (there is
    // nothing to destroy). Incompatible schemas open a native recovery dialog
    // (migrate / recreate-from-backup / quit) instead of exiting silently —
    // a bare `Err` here is invisible on a console-less Windows launch.
    let Some(ready) = ensure_database(&db_path)? else {
        // Quit by explicit choice (or after an already-reported failure).
        return Ok(());
    };
    if ready.created {
        eprintln!("database created: {}", db_path.display());
    }

    let main = MainWindow::new()?;
    // Apply UI font scaling from config (QuadHD comfort) via MainWindow -> Theme binding.
    main.set_ui_scale(cfg.ui.font_scale as f32);
    main.set_ui_min_px(cfg.ui.min_font_px as i32);
    // Restore persisted window geometry and splitter/column sizes. Values are
    // stored in logical px (already divided by the scale factor at save time)
    // and splitter lengths as ratios of the window box, so a layout saved on
    // one display still lands proportionally on another.
    let persisted = ui_persist::load(config_path);
    let (base_w, base_h) = match &persisted {
        Some(p) if p.window.width.is_some() && p.window.height.is_some() => {
            let w = p.window.width.unwrap_or(1400.0);
            let h = p.window.height.unwrap_or(800.0);
            let (sw, sh) = primary_screen_px();
            let sf = main.window().scale_factor().max(0.5);
            let max_w = if sw > 0 { sw as f32 / sf } else { w };
            let max_h = if sh > 0 { sh as f32 / sf } else { h };
            let cw = w.clamp(1240.0, max_w.max(1240.0));
            let ch = h.clamp(680.0, max_h.max(680.0));
            main.window().set_size(slint::LogicalSize::new(cw, ch));
            // Validate the saved position against the current display: after
            // a monitor change an unrestored (x, y) can land fully
            // off-screen. A maximized window's saved geometry is its
            // fullscreen rect, so position is only applied when not maximized.
            let maximized = p.window.maximized.unwrap_or(false);
            if !maximized && let (Some(x), Some(y)) = (p.window.x, p.window.y) {
                let (sw, sh) = primary_screen_px();
                let (lw, lh) = (sw as f32 / sf, sh as f32 / sf);
                // Keep at least a 100px corner of the window visible.
                let (xf, yf) = (x as f32, y as f32);
                let x_ok = xf > -cw + 100.0 && (lw <= 0.0 || xf < lw - 100.0);
                let y_ok = yf > -ch + 100.0 && (lh <= 0.0 || yf < lh - 100.0);
                if x_ok && y_ok {
                    main.window()
                        .set_position(slint::LogicalPosition::new(xf, yf));
                }
            }
            if maximized {
                main.window().set_maximized(true);
            }
            (cw, ch)
        }
        _ => {
            let (fw, fh) = first_launch_window_size(&main);
            main.window().set_size(slint::LogicalSize::new(fw, fh));
            (fw, fh)
        }
    };
    if let Some(persisted) = persisted {
        let ratio = |v: Option<f32>| v.filter(|r| (0.05..=0.95).contains(r));
        if let Some(r) = ratio(persisted.splits.images_table_split_ratio) {
            main.set_images_table_split(clamp_split(r * base_w, base_w));
        }
        if let Some(r) = ratio(persisted.splits.images_preview_h_ratio) {
            main.set_images_preview_h(clamp_split(r * base_h, base_h));
        }
        if let Some(r) = ratio(persisted.splits.review_main_split_ratio) {
            main.set_review_main_split(clamp_split(r * base_w, base_w));
        }
        if let Some(r) = ratio(persisted.splits.review_preview_h_ratio) {
            main.set_review_preview_h(clamp_split(r * base_h, base_h));
        }
        if let Some(r) = ratio(persisted.splits.detail_preview_split_ratio) {
            main.set_detail_preview_split(clamp_split(r * base_w, base_w));
        }
        if let Some(r) = ratio(persisted.splits.debug_table_h_ratio) {
            main.set_debug_table_h(clamp_split(r * base_h, base_h));
        }
        if let Some(r) = ratio(persisted.splits.process_progress_h_ratio) {
            main.set_process_progress_h(clamp_split(r * base_h, base_h));
        }
        // Column widths are persisted as logical lengths keyed per column.
        let col = |k: &str| {
            persisted
                .columns
                .get(k)
                .copied()
                .map(|v| v.clamp(44.0, 2000.0))
        };
        if let Some(v) = col("images.name") {
            main.set_images_col_name_w(v);
        }
        if let Some(v) = col("images.semantic") {
            main.set_images_col_semantic_w(v);
        }
        if let Some(v) = col("images.best") {
            main.set_images_col_best_w(v);
        }
        if let Some(v) = col("review.decision") {
            main.set_review_col_decision_w(v);
        }
        if let Some(v) = col("review.driver") {
            main.set_review_col_driver_w(v);
        }
        if let Some(v) = col("bestlaps.driver") {
            main.set_bestlaps_col_driver_w(v);
        }
        if let Some(v) = col("bestlaps.car") {
            main.set_bestlaps_col_car_w(v);
        }
        if let Some(v) = col("bestlaps.source") {
            main.set_bestlaps_col_source_w(v);
        }
        if let Some(v) = col("debug.image") {
            main.set_debug_col_image_w(v);
        }
    }
    main.set_app_version(forza_app::APP_VERSION.into());
    let inventory_model = Rc::new(VecModel::<ImageItem>::from(Vec::new()));
    main.set_images(ModelRc::from(inventory_model.clone()));
    LIST_MODEL.with(|slot| *slot.borrow_mut() = Some(inventory_model.clone()));
    let review_model = Rc::new(VecModel::<ReviewItem>::from(Vec::new()));
    main.set_reviews(ModelRc::from(review_model.clone()));
    REVIEW_MODEL.with(|slot| *slot.borrow_mut() = Some(review_model));
    let bestlap_model = Rc::new(VecModel::<BestLapItem>::from(Vec::new()));
    main.set_best_laps(ModelRc::from(bestlap_model.clone()));
    BESTLAP_MODEL.with(|slot| *slot.borrow_mut() = Some(bestlap_model));
    GAMERTAG.with(|slot| *slot.borrow_mut() = cfg.gamertag.clone());
    main.set_best_laps_gamertag(cfg.gamertag.clone().into());
    // Ensure filter defaults are "all" so cascade options start complete.
    BESTLAP_FILTER.with(|slot| {
        let mut f = slot.borrow_mut();
        f.dirty = "all".to_string();
        f.source = "all".to_string();
    });
    CONFIG_PATH.with(|slot| *slot.borrow_mut() = config_path.to_path_buf());

    // Run log model + params snapshot for the extraction runner.
    let run_log_model = Rc::new(VecModel::<slint::SharedString>::from(Vec::new()));
    main.set_run_log(ModelRc::from(run_log_model.clone()));
    RUN_LOG.with(|slot| *slot.borrow_mut() = Some(run_log_model));
    RUN_CONFIG
        .with(|slot| *slot.borrow_mut() = Some(forza_app::RunParams::from_config(&cfg, false)));
    main.set_run_info(run_info_line(&cfg).into());

    // Detail + settings + debug models.
    let detail_lap_model = Rc::new(VecModel::<DetailLapItem>::from(Vec::new()));
    main.set_detail_laps(ModelRc::from(detail_lap_model.clone()));
    DETAIL_LAP_MODEL.with(|slot| *slot.borrow_mut() = Some(detail_lap_model));
    let detail_review_model = Rc::new(VecModel::<DetailReviewItem>::from(Vec::new()));
    main.set_detail_reviews(ModelRc::from(detail_review_model.clone()));
    DETAIL_REVIEW_MODEL.with(|slot| *slot.borrow_mut() = Some(detail_review_model));
    let detail_result_model = Rc::new(VecModel::<DetailResultItem>::from(Vec::new()));
    main.set_detail_results(ModelRc::from(detail_result_model.clone()));
    DETAIL_RESULT_MODEL.with(|slot| *slot.borrow_mut() = Some(detail_result_model));
    let detail_attempt_model = Rc::new(VecModel::<DetailAttemptItem>::from(Vec::new()));
    main.set_detail_attempts(ModelRc::from(detail_attempt_model.clone()));
    DETAIL_ATTEMPT_MODEL.with(|slot| *slot.borrow_mut() = Some(detail_attempt_model));
    let settings_model = Rc::new(VecModel::<SettingItem>::from(Vec::new()));
    main.set_settings_rows(ModelRc::from(settings_model.clone()));
    SETTINGS_MODEL.with(|slot| *slot.borrow_mut() = Some(settings_model));
    let debug_case_model = Rc::new(VecModel::<DebugCaseItem>::from(Vec::new()));
    main.set_debug_cases(ModelRc::from(debug_case_model.clone()));
    DEBUG_CASE_MODEL.with(|slot| *slot.borrow_mut() = Some(debug_case_model));
    let debug_result_model = Rc::new(VecModel::<DebugResultComboItem>::from(Vec::new()));
    main.set_debug_results(ModelRc::from(debug_result_model.clone()));
    DEBUG_RESULT_MODEL.with(|slot| *slot.borrow_mut() = Some(debug_result_model));
    main.set_doctor_checks(ModelRc::from(Rc::new(VecModel::<DoctorCheckItem>::from(
        Vec::new(),
    ))));
    main.set_doctor_overall("PASS".into());
    main.set_doctor_summary("Not checked".into());
    main.set_overview_lm_level("info".into());
    main.set_overview_lm_message("Not checked".into());
    main.set_logs_status("".into());

    // Context header values.
    // Surface the exact database file in use (absolute): with no more
    // silent fallbacks, this line is the single source of truth and must
    // never show a surprising path.
    let db_display = db_path.canonicalize().unwrap_or_else(|_| db_path.clone());
    main.set_context_db(db_display.display().to_string().into());
    main.set_context_gamertag(cfg.gamertag.clone().into());

    // Worker thread owns the receiver; responses marshal back to this loop.
    let (tx, rx) = mpsc::channel::<Request>();
    {
        let ui = main.as_weak();
        let ctx = WorkerContext::new(db_path.clone(), config_path.to_path_buf(), cfg.clone());
        worker::spawn_thread(rx, ctx, move |response| {
            let ui = ui.clone();
            let _ = slint::invoke_from_event_loop(move || callbacks::handle_response(response, ui));
        });
    }

    // Global sender slot so page callbacks can enqueue requests.
    WORKER_TX.with(|slot| {
        let _ = slot.set(tx);
    });

    // ── Page callbacks (wiring lives in `callbacks`, grouped by page) ──
    callbacks::wire_inventory(&main);
    callbacks::wire_review(&main);
    callbacks::wire_bestlaps(&main);
    callbacks::wire_maintenance(&main);
    callbacks::wire_detail(&main);
    callbacks::wire_settings(&main);
    callbacks::wire_debug(&main);
    callbacks::wire_logs(&main);
    callbacks::wire_about(&main);
    callbacks::wire_run(&main);

    // Review page reference data (track correction combo + class list).
    {
        let refs = forza_domain::reference_data::embedded_reference_data();
        let mut tracks: Vec<slint::SharedString> =
            refs.tracks.iter().cloned().map(Into::into).collect();
        tracks.sort_by_key(|t| t.to_lowercase());
        callbacks::set_review_track_model(&main, tracks);
        let classes: Vec<slint::SharedString> = forza_domain::enums::RaceClass::ALL
            .iter()
            .map(|c| slint::SharedString::from(c.as_str()))
            .collect();
        callbacks::set_review_class_model(&main, classes);
    }

    // Persist window geometry and splitter state on close
    {
        let cfg_path = config_path.to_path_buf();
        let weak = main.as_weak();
        main.window().on_close_requested(move || {
            if let Some(w) = weak.upgrade() {
                let sf = w.window().scale_factor().max(0.5);
                // size/position come back in physical px; store logical so the
                // saved state survives DPI changes between sessions.
                let size = w.window().size();
                let pos = w.window().position();
                let lw = size.width as f32 / sf;
                let lh = size.height as f32 / sf;
                let ratio_h = |v: f32| (v / lw).clamp(0.05, 0.95);
                let ratio_v = |v: f32| (v / lh).clamp(0.05, 0.95);
                // A maximized window reports its fullscreen rect: persisting
                // that as x/y would poison the next restore on a smaller
                // display. Keep position only for normal windows.
                let is_max = w.window().is_maximized();
                let state = ui_persist::UiPersist {
                    window: ui_persist::WindowState {
                        width: Some(lw),
                        height: Some(lh),
                        x: (!is_max).then(|| (pos.x as f32 / sf).round() as i32),
                        y: (!is_max).then(|| (pos.y as f32 / sf).round() as i32),
                        maximized: Some(is_max),
                    },
                    splits: ui_persist::SplitState {
                        images_table_split_ratio: Some(ratio_h(w.get_images_table_split())),
                        images_preview_h_ratio: Some(ratio_v(w.get_images_preview_h())),
                        review_main_split_ratio: Some(ratio_h(w.get_review_main_split())),
                        review_preview_h_ratio: Some(ratio_v(w.get_review_preview_h())),
                        detail_preview_split_ratio: Some(ratio_h(w.get_detail_preview_split())),
                        debug_table_h_ratio: Some(ratio_v(w.get_debug_table_h())),
                        process_progress_h_ratio: Some(ratio_v(w.get_process_progress_h())),
                    },
                    columns: {
                        let mut cols = std::collections::HashMap::new();
                        cols.insert("images.name".to_string(), w.get_images_col_name_w());
                        cols.insert("images.semantic".to_string(), w.get_images_col_semantic_w());
                        cols.insert("images.best".to_string(), w.get_images_col_best_w());
                        cols.insert("review.decision".to_string(), w.get_review_col_decision_w());
                        cols.insert("review.driver".to_string(), w.get_review_col_driver_w());
                        cols.insert("bestlaps.driver".to_string(), w.get_bestlaps_col_driver_w());
                        cols.insert("bestlaps.car".to_string(), w.get_bestlaps_col_car_w());
                        cols.insert("bestlaps.source".to_string(), w.get_bestlaps_col_source_w());
                        cols.insert("debug.image".to_string(), w.get_debug_col_image_w());
                        cols
                    },
                };
                let _ = ui_persist::save(&cfg_path, &state);
            }
            slint::CloseRequestResponse::HideWindow
        });
    }

    // Initial load (single inventory request — mirrors Python's
    // ImageController which refreshes from DB on startup and only scans on
    // demand).
    main.set_status_text("loading…".into());
    {
        let filter = ImageInventoryFilter::default();
        remember_inventory_filter(&filter);
        INVENTORY_REFRESH_IN_FLIGHT.with(|f| f.set(true));
        send_request(Request::RefreshInventory { filter });
    }
    send_request(Request::ListReviews {
        filter: ReviewQueueFilter {
            bucket: "open".into(),
            ..Default::default()
        },
    });
    send_request(Request::ListBestLaps);

    main.run()?;
    Ok(())
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::{RecoveryChoice, ensure_database, resolve_incompatible};

    #[test]
    fn missing_database_is_created_from_zero() {
        let dir = tempfile::tempdir().unwrap();
        let db = dir.path().join("fresh.sqlite3");
        assert!(!db.exists());
        let ready = ensure_database(&db).unwrap().expect("no dialog on empty");
        assert!(ready.created);
        // Second call is a no-op on the now-current database.
        let again = ensure_database(&db).unwrap().expect("no dialog on current");
        assert!(!again.created);
        assert!(matches!(
            forza_db::migration::schema_status(&db).unwrap(),
            forza_db::migration::SchemaStatus::Current
        ));
    }

    fn foreign_database(dir: &tempfile::TempDir, name: &str, version: i64) -> std::path::PathBuf {
        let db = dir.path().join(name);
        ensure_database(&db).unwrap();
        let conn = forza_db::open_connection(&db).unwrap();
        conn.execute_batch(&format!("PRAGMA user_version = {version}"))
            .unwrap();
        drop(conn);
        db
    }

    #[test]
    fn quit_leaves_incompatible_database_untouched() {
        let dir = tempfile::tempdir().unwrap();
        let db = foreign_database(&dir, "foreign.sqlite3", 424242);
        let done = resolve_incompatible(&db, RecoveryChoice::Quit).unwrap();
        assert!(done.is_none());
        assert!(matches!(
            forza_db::migration::schema_status(&db).unwrap(),
            forza_db::migration::SchemaStatus::Incompatible { found: 424242 }
        ));
    }

    #[test]
    fn unknown_versions_cannot_migrate_but_can_recreate() {
        let dir = tempfile::tempdir().unwrap();
        let db = foreign_database(&dir, "foreign.sqlite3", 424242);
        let err = resolve_incompatible(&db, RecoveryChoice::Migrate)
            .unwrap_err()
            .to_string();
        assert!(err.contains("no migration path"), "{err}");
        // A backup was still made before the failed migration.
        assert_eq!(std::fs::read_dir(dir.path()).unwrap().count(), 2);

        let done = resolve_incompatible(&db, RecoveryChoice::Recreate).unwrap();
        assert!(matches!(done, Some(super::RecoveryDone::Recreated { .. })));
        assert!(matches!(
            forza_db::migration::schema_status(&db).unwrap(),
            forza_db::migration::SchemaStatus::Current
        ));
    }

    #[test]
    fn v2_database_migrates_with_data_preserved() {
        let dir = tempfile::tempdir().unwrap();
        let db = dir.path().join("v2.sqlite3");
        ensure_database(&db).unwrap();
        let conn = forza_db::open_connection(&db).unwrap();
        conn.execute_batch(
            "ALTER TABLE extraction_runs ADD COLUMN performance_tps_floor FLOAT;
             ALTER TABLE extraction_runs ADD COLUMN performance_reload_elapsed_s FLOAT;
             ALTER TABLE extraction_runs ADD COLUMN performance_reload_streak INTEGER;
             INSERT INTO extraction_runs (id, model, created_at)
              VALUES ('run-v2', 'm', datetime('now'));
             PRAGMA user_version = 2;",
        )
        .unwrap();
        drop(conn);

        let done = resolve_incompatible(&db, RecoveryChoice::Migrate).unwrap();
        assert!(matches!(done, Some(super::RecoveryDone::Migrated { .. })));
        assert!(matches!(
            forza_db::migration::schema_status(&db).unwrap(),
            forza_db::migration::SchemaStatus::Current
        ));
        let conn = forza_db::open_connection(&db).unwrap();
        let count: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM extraction_runs WHERE id = 'run-v2'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(count, 1);
    }
}
