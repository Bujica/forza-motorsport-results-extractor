//! forza-gui: Slint front-end of the Rust line (Fase 4 slice + F10 pages).
//!
//! Threading contract (migration plan §4.9): the Tokio runtime lives on a
//! dedicated worker thread; Slint callbacks are synchronous and only enqueue
//! typed requests; results come back to the UI thread through
//! `slint::invoke_from_event_loop`. Widget-adjacent state (`Rc` models, row
//! cache) lives in UI-thread locals and is never shared across threads.

pub mod worker;

use std::cell::RefCell;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::rc::Rc;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::mpsc;

use slint::{Image, Model, ModelRc, VecModel};

use crate::worker::{Request, Response, WorkerContext};
use forza_app::{ImageInventoryEntry, ImageInventoryFilter};

slint::include_modules!();

thread_local! {
    static LIST_MODEL: RefCell<Option<Rc<VecModel<ImageItem>>>> = const { RefCell::new(None) };
    static ROW_CACHE: RefCell<Vec<ImageInventoryEntry>> = const { RefCell::new(Vec::new()) };
    static REVIEW_MODEL: RefCell<Option<Rc<VecModel<ReviewItem>>>> = const { RefCell::new(None) };
    static BESTLAP_MODEL: RefCell<Option<Rc<VecModel<BestLapItem>>>> = const { RefCell::new(None) };
    static GAMERTAG: RefCell<String> = const { RefCell::new(String::new()) };
    static RUN_LOG: RefCell<Option<Rc<VecModel<slint::SharedString>>>> = const { RefCell::new(None) };
    static RUN_CANCEL: RefCell<Option<Arc<AtomicBool>>> = const { RefCell::new(None) };
    static RUN_CONFIG: RefCell<Option<forza_app::RunParams>> = const { RefCell::new(None) };
    static DETAIL_CACHE: RefCell<Option<forza_app::ImageDetailData>> = const { RefCell::new(None) };
    static DETAIL_INDEX: RefCell<i32> = const { RefCell::new(-1) };
    static DETAIL_LAP_MODEL: RefCell<Option<Rc<VecModel<DetailLapItem>>>> = const { RefCell::new(None) };
    static DETAIL_REVIEW_MODEL: RefCell<Option<Rc<VecModel<DetailReviewItem>>>> = const { RefCell::new(None) };
    static DETAIL_RESULT_MODEL: RefCell<Option<Rc<VecModel<DetailResultItem>>>> = const { RefCell::new(None) };
    static DETAIL_ATTEMPT_MODEL: RefCell<Option<Rc<VecModel<DetailAttemptItem>>>> = const { RefCell::new(None) };
    static SETTINGS_MODEL: RefCell<Option<Rc<VecModel<SettingItem>>>> = const { RefCell::new(None) };
    static PENDING_SETTINGS: RefCell<BTreeMap<String, String>> =
        const { RefCell::new(BTreeMap::new()) };
    static SETTINGS_LOADED: RefCell<bool> = const { RefCell::new(false) };
    static CONFIG_PATH: RefCell<PathBuf> = const { RefCell::new(PathBuf::new()) };
}

fn append_run_log(line: String) {
    RUN_LOG.with(|slot| {
        if let Some(model) = slot.borrow().as_ref() {
            model.push(line.into());
            while model.row_count() > 500 {
                model.remove(0);
            }
        }
    });
}

fn set_status(ui: &MainWindow, text: &str) {
    ui.set_status_text(text.into());
}

fn run_info_line(cfg: &forza_config::AppConfig) -> String {
    format!(
        "{} · {} · prompt {} · {} · ctx {} · grayscale {}",
        cfg.llm.url,
        cfg.llm.model,
        cfg.prompt.active,
        cfg.llm.image_format,
        cfg.llm.context_length.unwrap_or(5000),
        if cfg.image.grayscale { "on" } else { "off" }
    )
}

/// Launch the GUI. Blocks until the window closes.
pub fn run(config_path: &Path) -> anyhow::Result<()> {
    let (cfg, warnings) = forza_config::load_config(config_path, false)?;
    for warning in warnings {
        eprintln!("config warning: {warning}");
    }
    forza_config::validate_config(&cfg)
        .map_err(|errors| anyhow::anyhow!("configuration invalid: {}", errors.join("; ")))?;

    let db_path: PathBuf = cfg.database_file.clone();
    if !db_path.exists() {
        return Err(anyhow::anyhow!(
            "database {} does not exist; run `forza maintenance db-upgrade` first",
            db_path.display()
        ));
    }

    let main = MainWindow::new()?;
    let inventory_model = Rc::new(VecModel::<ImageItem>::from(Vec::new()));
    main.set_images(ModelRc::from(inventory_model.clone()));
    LIST_MODEL.with(|slot| *slot.borrow_mut() = Some(inventory_model.clone()));
    GAMERTAG.with(|slot| *slot.borrow_mut() = cfg.gamertag.clone());
    CONFIG_PATH.with(|slot| *slot.borrow_mut() = config_path.to_path_buf());

    // Run log model + params snapshot for the extraction runner.
    let run_log_model = Rc::new(VecModel::<slint::SharedString>::from(Vec::new()));
    main.set_run_log(ModelRc::from(run_log_model.clone()));
    RUN_LOG.with(|slot| *slot.borrow_mut() = Some(run_log_model));
    RUN_CONFIG
        .with(|slot| *slot.borrow_mut() = Some(forza_app::RunParams::from_config(&cfg, false)));
    main.set_run_info(run_info_line(&cfg).into());

    // Detail + settings models.
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

    // Context header values.
    main.set_context_db(db_path.display().to_string().into());
    main.set_context_gamertag(cfg.gamertag.clone().into());

    // Worker thread owns the receiver; responses marshal back to this loop.
    let (tx, rx) = mpsc::channel::<Request>();
    {
        let ui = main.as_weak();
        let ctx = WorkerContext::new(db_path.clone(), config_path.to_path_buf(), cfg.clone());
        worker::spawn_thread(rx, ctx, move |response| {
            let ui = ui.clone();
            let _ = slint::invoke_from_event_loop(move || match response {
                Response::Inventory {
                    result,
                    filter_label,
                } => match result {
                    Ok(entries) => {
                        let count = entries.len();
                        ROW_CACHE.with(|slot| *slot.borrow_mut() = entries.clone());
                        LIST_MODEL.with(|slot| {
                            if let Some(model) = slot.borrow().as_ref() {
                                let items: Vec<ImageItem> = entries
                                    .iter()
                                    .map(|e| ImageItem {
                                        id: e.id.clone().into(),
                                        name: e.name.clone().into(),
                                        processing: e.processing_status.clone().into(),
                                        best_lap: e.best_lap_status.clone().into(),
                                        file_status: e.file_status.clone().into(),
                                    })
                                    .collect();
                                model.set_vec(items);
                            }
                        });
                        if let Some(w) = ui.upgrade() {
                            w.set_status_text(format!("{count} image(s) [{filter_label}]").into());
                        }
                    }
                    Err(message) => {
                        if let Some(w) = ui.upgrade() {
                            w.set_status_text(format!("error: {message}").into());
                        }
                    }
                },
                Response::Reviews { result, bucket } => {
                    REVIEW_MODEL.with(|slot| {
                        if let Some(model) = slot.borrow().as_ref()
                            && let Ok(entries) = &result
                        {
                            let items: Vec<ReviewItem> = entries
                                .iter()
                                .map(|c| ReviewItem {
                                    number: c.case_number as i32,
                                    reason: c.reason.clone().into(),
                                    trigger: c.trigger.clone().unwrap_or_default().into(),
                                    driver: c.driver.clone().unwrap_or_default().into(),
                                    track: c.track.clone().unwrap_or_default().into(),
                                    model_value: c.model_value.clone().unwrap_or_default().into(),
                                    status: c.status.clone().into(),
                                })
                                .collect();
                            model.set_vec(items);
                        }
                    });
                    if let Some(w) = ui.upgrade() {
                        match result {
                            Ok(list) => w.set_status_text(
                                format!("{} review case(s) [{}]", list.len(), bucket).into(),
                            ),
                            Err(message) => w.set_status_text(format!("error: {message}").into()),
                        }
                    }
                }
                Response::CaseDecided(result) => {
                    let ok = result.is_ok();
                    if let Some(w) = ui.upgrade() {
                        w.set_status_text(match result {
                            Ok(()) => "case updated; derived state rebuilt".into(),
                            Err(message) => format!("error: {message}").into(),
                        });
                    }
                    if ok {
                        // Refresh reviews + best laps after any decision.
                        send_request(Request::ListReviews {
                            bucket: "open".into(),
                        });
                        send_request(Request::ListBestLaps);
                    }
                }
                Response::BestLaps(result) => {
                    BESTLAP_MODEL.with(|slot| {
                        if let Some(model) = slot.borrow().as_ref()
                            && let Ok(rows) = &result
                        {
                            let items: Vec<BestLapItem> = rows
                                .iter()
                                .map(|b| BestLapItem {
                                    track: b.track.clone().into(),
                                    class: b.race_class.clone().into(),
                                    driver: b.driver.clone().into(),
                                    car: b.car.clone().into(),
                                    time: b.best_lap.clone().unwrap_or_default().into(),
                                    dirty: b.dirty,
                                    mine: b.mine,
                                })
                                .collect();
                            model.set_vec(items);
                        }
                    });
                    if let Some(w) = ui.upgrade() {
                        match result {
                            Ok(rows) => {
                                w.set_status_text(format!("{} best lap(s)", rows.len()).into())
                            }
                            Err(message) => w.set_status_text(format!("error: {message}").into()),
                        }
                    }
                }
                Response::Doctor(result) => {
                    if let Some(w) = ui.upgrade() {
                        match result {
                            Ok(summary) => {
                                w.set_doctor_report(
                                    format!(
                                        "schema: {} (user_version={})\nok: {}",
                                        summary.schema_status, summary.user_version, summary.ok
                                    )
                                    .into(),
                                );
                            }
                            Err(message) => w.set_doctor_report(format!("error: {message}").into()),
                        }
                    }
                }
                Response::RunDryRunDone(summary) => {
                    if let Some(w) = ui.upgrade() {
                        append_run_log(summary.clone());
                        set_status(&w, "dry-run complete");
                    }
                }
                Response::Rebuild(result) => {
                    if let Some(w) = ui.upgrade() {
                        match result {
                            Ok(outcome) => w.set_status_text(
                                format!(
                                    "rebuild: {} winner(s); reviews +{} kept {} auto-resolved {}",
                                    outcome.best_lap_winners,
                                    outcome.review_inserted,
                                    outcome.review_kept,
                                    outcome.review_auto_resolved
                                )
                                .into(),
                            ),
                            Err(message) => w.set_status_text(format!("error: {message}").into()),
                        }
                    }
                    send_request(Request::ListReviews {
                        bucket: "all".into(),
                    });
                    send_request(Request::ListBestLaps);
                }
                Response::ImageDetail(result) => match result {
                    Ok(Some(data)) => {
                        apply_image_detail(&ui, data);
                    }
                    Ok(None) => {
                        if let Some(w) = ui.upgrade() {
                            set_status(&w, "image not found");
                        }
                    }
                    Err(message) => {
                        if let Some(w) = ui.upgrade() {
                            set_status(&w, format!("error: {message}").as_str());
                        }
                    }
                },
                Response::Settings(result) => match result {
                    Ok(outcome) => {
                        apply_settings(&ui, outcome);
                    }
                    Err(message) => {
                        if let Some(w) = ui.upgrade() {
                            set_status(&w, format!("error: {message}").as_str());
                        }
                    }
                },
            });
        });
    }

    // Global sender slot so page callbacks can enqueue requests.
    WORKER_TX.with(|slot| {
        let _ = slot.set(tx);
    });

    // ── Page callbacks ────────────────────────────────────────────────────
    {
        let ui = main.as_weak();
        main.on_refresh_requested(move |filter_value| {
            let filter = ImageInventoryFilter {
                processing_status: (filter_value != "all").then(|| filter_value.to_string()),
                ..Default::default()
            };
            enqueue(
                Request::RefreshInventory { filter },
                &ui,
                &format!("loading ({filter_value})…"),
            );
        });
    }
    {
        let ui = main.as_weak();
        main.on_selection_changed(move |index| {
            ROW_CACHE.with(|rows| {
                let guard = rows.borrow();
                let Some(entry) = guard.get(index as usize) else { return };
                if let Some(w) = ui.upgrade() {
                    w.set_detail_title(entry.name.clone().into());
                    w.set_detail_lines(
                        format!(
                            "id: {}\nfile_status: {}\nbest_lap_status: {}\nprocessing: {}\nsize: {}",
                            entry.id,
                            entry.file_status,
                            entry.best_lap_status,
                            entry.processing_status,
                            entry
                                .size_bytes
                                .map(|b| format!("{b} bytes"))
                                .unwrap_or_else(|| "-".into()),
                        )
                        .into(),
                    );
                }
            });
        });
    }
    {
        let ui = main.as_weak();
        main.on_reviews_requested(move |bucket| {
            enqueue(
                Request::ListReviews {
                    bucket: bucket.to_string(),
                },
                &ui,
                "loading reviews…",
            );
        });
    }
    {
        let ui = main.as_weak();
        main.on_case_decided(move |case_number, field, value| {
            enqueue(
                Request::DecideCase {
                    case_number: case_number as i64,
                    field: field.into(),
                    value: value.into(),
                },
                &ui,
                "applying correction…",
            );
        });
    }
    {
        let ui = main.as_weak();
        main.on_case_ignored(move |case_number| {
            enqueue(
                Request::IgnoreCase {
                    case_number: case_number as i64,
                },
                &ui,
                "ignoring case…",
            );
        });
    }
    {
        let ui = main.as_weak();
        main.on_bestlaps_requested(move || {
            enqueue(Request::ListBestLaps, &ui, "loading best laps…");
        });
    }
    {
        let ui = main.as_weak();
        main.on_doctor_requested(move || {
            enqueue(Request::RunDoctor, &ui, "running doctor…");
        });
    }
    {
        let ui = main.as_weak();
        main.on_rebuild_requested(move || {
            enqueue(Request::RunRebuild, &ui, "rebuilding derived state…");
        });
    }
    {
        let ui = main.as_weak();
        main.on_open_image_detail(move |index| {
            let id = ROW_CACHE.with(|rows| rows.borrow().get(index as usize).map(|e| e.id.clone()));
            let Some(id) = id else { return };
            DETAIL_INDEX.with(|slot| *slot.borrow_mut() = index);
            if let Some(w) = ui.upgrade() {
                w.set_page("image-detail".into());
                w.set_detail_loaded(false);
                set_status(&w, "loading image detail…");
            }
            send_request(Request::LoadImageDetail { image_id: id });
        });
    }
    {
        let ui = main.as_weak();
        main.on_detail_tab_changed(move |tab| {
            if let Some(w) = ui.upgrade() {
                w.set_detail_tab(tab);
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_detail_prev(move || step_detail(&ui, -1));
    }
    {
        let ui = main.as_weak();
        main.on_detail_next(move || step_detail(&ui, 1));
    }
    {
        let ui = main.as_weak();
        main.on_detail_close(move || {
            if let Some(w) = ui.upgrade() {
                w.set_page("images".into());
            }
        });
    }
    {
        main.on_page_changed(move |page| {
            // Lazy settings load on first entry (GUI state rules).
            if page == "settings" && !SETTINGS_LOADED.with(|slot| *slot.borrow()) {
                SETTINGS_LOADED.with(|slot| *slot.borrow_mut() = true);
                send_request(Request::LoadSettings);
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_setting_edited(move |key, value| {
            PENDING_SETTINGS.with(|slot| {
                slot.borrow_mut().insert(key.to_string(), value.to_string());
            });
            let changes = PENDING_SETTINGS.with(|slot| slot.borrow().clone());
            enqueue(Request::PreviewSettings { changes }, &ui, "validating…");
        });
    }
    {
        let ui = main.as_weak();
        main.on_discard_settings(move || {
            PENDING_SETTINGS.with(|slot| slot.borrow_mut().clear());
            enqueue(Request::LoadSettings, &ui, "reloading settings…");
        });
    }
    {
        let ui = main.as_weak();
        main.on_save_settings(move || {
            let changes = PENDING_SETTINGS.with(|slot| slot.borrow().clone());
            if changes.is_empty() {
                return;
            }
            enqueue(Request::SaveSettings { changes }, &ui, "saving settings…");
        });
    }

    // ── Live extraction runner (own thread, cooperative cancel) ──────────
    {
        let ui = main.as_weak();
        main.on_start_run(move |dry_run, force, _retry| {
            if dry_run {
                let input_dir = RUN_CONFIG
                    .with(|slot| slot.borrow().as_ref().map(|p| p.input_dir.to_string_lossy().to_string()))
                    .unwrap_or_default();
                enqueue(
                    Request::RunDryRun { input_dir },
                    &ui,
                    "dry-run: planning only…",
                );
                return;
            }
            let already_running = RUN_CANCEL.with(|slot| slot.borrow().is_some());
            if already_running {
                if let Some(w) = ui.upgrade() {
                    set_status(&w, "a run is already active");
                }
                return;
            }
            let Some(params) = RUN_CONFIG.with(|slot| slot.borrow().clone()) else { return };
            let params = forza_app::RunParams { force, ..params };
            let cancel = Arc::new(AtomicBool::new(false));
            RUN_CANCEL.with(|slot| *slot.borrow_mut() = Some(cancel.clone()));
            if let Some(w) = ui.upgrade() {
                w.set_run_running(true);
                w.set_run_done(0);
                w.set_run_total(0);
                w.set_run_percent(0.0);
            }
            append_run_log(format!("[start] model={} force={}", params.model, params.force));

            let ui = ui.clone();
            let _handle = forza_app::spawn_extraction(params, cancel, move |event| {
                let ui = ui.clone();
                let _ = slint::invoke_from_event_loop(move || match event {
                    forza_app::RunEvent::Started { run_id, total } => {
                        append_run_log(format!("[run {run_id}] {total} file(s) considered"));
                        if let Some(w) = ui.upgrade() {
                            w.set_run_total(total as i32);
                        }
                    }
                    forza_app::RunEvent::Plan { new, cached, batch, existing, skipped } => {
                        append_run_log(format!(
                            "plan: new={new} cached={cached} batch={batch} existing={existing} skipped={skipped}"
                        ));
                    }
                    forza_app::RunEvent::ImageStarted { name } => {
                        append_run_log(format!("→ {name}"));
                    }
                    forza_app::RunEvent::ImageDone { name, ok, laps } => {
                        append_run_log(format!(
                            "  {} {name} ({laps} lap(s))",
                            if ok { "✓" } else { "✗" }
                        ));
                    }
                    forza_app::RunEvent::Progress { done, total } => {
                        if let Some(w) = ui.upgrade() {
                            w.set_run_done(done as i32);
                            w.set_run_total(total as i32);
                            let percent = if total > 0 {
                                (done as f32 / total as f32) * 100.0
                            } else {
                                0.0
                            };
                            w.set_run_percent(percent);
                        }
                    }
                    forza_app::RunEvent::Log(line) => append_run_log(line),
                    forza_app::RunEvent::Finished { cancelled, processed, succeeded, failed, elapsed_s } => {
                        append_run_log(format!(
                            "[done] cancelled={cancelled} processed={processed} ok={succeeded} fail={failed} in {elapsed_s:.1}s"
                        ));
                        RUN_CANCEL.with(|slot| *slot.borrow_mut() = None);
                        if let Some(w) = ui.upgrade() {
                            w.set_run_running(false);
                            w.set_run_percent(100.0);
                        }
                        // Refresh derived views after a run.
                        send_request(Request::RefreshInventory {
                            filter: ImageInventoryFilter::default(),
                        });
                        send_request(Request::ListBestLaps);
                        send_request(Request::ListReviews { bucket: "open".into() });
                    }
                    forza_app::RunEvent::Failed(message) => {
                        append_run_log(format!("[failed] {message}"));
                        RUN_CANCEL.with(|slot| *slot.borrow_mut() = None);
                        if let Some(w) = ui.upgrade() {
                            w.set_run_running(false);
                            set_status(&w, format!("run failed: {message}").as_str());
                        }
                    }
                });
            });
        });
    }
    {
        let ui = main.as_weak();
        main.on_cancel_run(move || {
            RUN_CANCEL.with(|slot| {
                if let Some(cancel) = slot.borrow().as_ref() {
                    cancel.store(true, std::sync::atomic::Ordering::Relaxed);
                    if let Some(w) = ui.upgrade() {
                        set_status(&w, "cancellation requested…");
                    }
                }
            });
        });
    }

    // Initial load.
    main.set_status_text("loading…".into());
    send_request(Request::RefreshInventory {
        filter: ImageInventoryFilter::default(),
    });
    send_request(Request::ListReviews {
        bucket: "open".into(),
    });

    main.run()?;
    Ok(())
}

/// Navigate to the previous/next image inside the detail page.
fn step_detail(ui: &slint::Weak<MainWindow>, delta: i32) {
    let index = DETAIL_INDEX.with(|slot| *slot.borrow()) + delta;
    let count = ROW_CACHE.with(|rows| rows.borrow().len()) as i32;
    if index < 0 || index >= count {
        return;
    }
    if let Some(w) = ui.upgrade() {
        w.set_selected_index(index);
    }
    if let Some(cb) = ui.upgrade() {
        cb.invoke_open_image_detail(index);
    }
}

/// Fill the detail page models from the loaded bundle (UI thread only).
fn apply_image_detail(ui: &slint::Weak<MainWindow>, data: forza_app::ImageDetailData) {
    use forza_app::ImageDetailData as Data;
    let Data {
        meta,
        laps,
        reviews,
        results,
        attempts,
    } = data;

    DETAIL_LAP_MODEL.with(|slot| {
        if let Some(model) = slot.borrow().as_ref() {
            let items: Vec<DetailLapItem> = laps
                .iter()
                .map(|l| DetailLapItem {
                    index: l.lap_index as i32,
                    track: l.track.clone().into(),
                    class: l.race_class.clone().into(),
                    driver: l.driver.clone().into(),
                    car: l.car.clone().into(),
                    time: l.best_lap.clone().into(),
                    flags: if l.is_best_lap {
                        "best".into()
                    } else if l.dirty {
                        "dirty".into()
                    } else {
                        "—".into()
                    },
                    dirty: l.dirty,
                    best: l.is_best_lap,
                })
                .collect();
            model.set_vec(items);
        }
    });
    DETAIL_REVIEW_MODEL.with(|slot| {
        if let Some(model) = slot.borrow().as_ref() {
            let items: Vec<DetailReviewItem> = reviews
                .iter()
                .map(|c| DetailReviewItem {
                    number: c.case_number as i32,
                    reason: c.reason.clone().into(),
                    trigger: c.trigger.clone().unwrap_or_default().into(),
                    driver: c.driver.clone().unwrap_or_default().into(),
                    track: c.track.clone().unwrap_or_default().into(),
                    model_value: c.model_value.clone().unwrap_or_default().into(),
                    status: c.status.clone().into(),
                })
                .collect();
            model.set_vec(items);
        }
    });
    DETAIL_RESULT_MODEL.with(|slot| {
        if let Some(model) = slot.borrow().as_ref() {
            let items: Vec<DetailResultItem> = results
                .iter()
                .map(|r| DetailResultItem {
                    run: r.run_id.clone().into(),
                    status: r.status.clone().into(),
                    model: r.model.clone().unwrap_or_default().into(),
                    attempts: r.attempt_count as i32,
                    duration: r
                        .duration_ms
                        .map(|ms| format!("{ms} ms"))
                        .unwrap_or_else(|| "—".into())
                        .into(),
                    tokens: r
                        .total_tokens
                        .map(|t| format!("{t} tok"))
                        .unwrap_or_else(|| "—".into())
                        .into(),
                    created: r.created_at.clone().into(),
                })
                .collect();
            model.set_vec(items);
        }
    });
    DETAIL_ATTEMPT_MODEL.with(|slot| {
        if let Some(model) = slot.borrow().as_ref() {
            let items: Vec<DetailAttemptItem> = attempts
                .iter()
                .map(|a| DetailAttemptItem {
                    number: a.attempt_number as i32,
                    reason: a.attempt_reason.clone().into(),
                    status: a.status.clone().into(),
                    accepted: a.accepted,
                    rejected: a.rejected_reason.clone().unwrap_or_default().into(),
                    model: a.model.clone().unwrap_or_default().into(),
                    duration: a
                        .duration_ms
                        .map(|ms| format!("{ms} ms"))
                        .unwrap_or_else(|| "—".into())
                        .into(),
                    tps: a
                        .tokens_per_second
                        .map(|t| format!("{t:.1} tok/s"))
                        .unwrap_or_else(|| "—".into())
                        .into(),
                    created: a.created_at.clone().into(),
                })
                .collect();
            model.set_vec(items);
        }
    });

    let meta_lines = format!(
        "id: {}\nhash: {}\nduplicate of: {}\ncurrent name: {}\nsemantic name: {}\nsize: {}\ndimensions: {} × {}\nbit depth: {}\ncolor mode: {}\nmime: {}\nformat: {}\nrace date: {} (source: {})\nfile status: {}\nbest lap status: {}\nprocessing: {}",
        meta.id,
        meta.file_hash,
        meta.duplicate_of_image_file_id
            .clone()
            .unwrap_or_else(|| "—".into()),
        meta.current_name.clone().unwrap_or_else(|| "—".into()),
        meta.semantic_name.clone().unwrap_or_else(|| "—".into()),
        meta.size_bytes
            .map(|b| format!("{b} bytes"))
            .unwrap_or_else(|| "—".into()),
        meta.width_px
            .map(|v| v.to_string())
            .unwrap_or_else(|| "?".into()),
        meta.height_px
            .map(|v| v.to_string())
            .unwrap_or_else(|| "?".into()),
        meta.bit_depth
            .map(|v| v.to_string())
            .unwrap_or_else(|| "—".into()),
        meta.color_mode.clone().unwrap_or_else(|| "—".into()),
        meta.mime_type.clone().unwrap_or_else(|| "—".into()),
        meta.image_format.clone().unwrap_or_else(|| "—".into()),
        meta.race_date.clone().unwrap_or_else(|| "—".into()),
        meta.race_datetime_source,
        meta.file_status,
        meta.best_lap_status,
        meta.processing_status,
    );

    // Preview: load the current file when it exists on disk.
    let preview = meta
        .current_path
        .as_ref()
        .filter(|p| Path::new(p).exists())
        .and_then(|p| Image::load_from_path(Path::new(p)).ok());
    let has_preview = preview.is_some();

    if let Some(w) = ui.upgrade() {
        w.set_detail_title(
            meta.current_name
                .clone()
                .unwrap_or_else(|| meta.id.clone())
                .into(),
        );
        w.set_detail_meta(meta_lines.into());
        w.set_detail_badges(
            format!(
                "file: {} · best: {} · processing: {}",
                meta.file_status, meta.best_lap_status, meta.processing_status
            )
            .into(),
        );
        w.set_detail_path(meta.current_path.clone().unwrap_or_default().into());
        w.set_detail_preview(preview.unwrap_or_default());
        w.set_detail_has_preview(has_preview);
        w.set_detail_tab("metadata".into());
        w.set_detail_loaded(true);
        set_status(&w, "image detail loaded");
    }
    DETAIL_CACHE.with(|slot| {
        *slot.borrow_mut() = Some(forza_app::ImageDetailData {
            meta,
            laps,
            reviews,
            results,
            attempts,
        });
    });
}

/// Apply a settings load/preview/save outcome to the page and dependent UI.
fn apply_settings(ui: &slint::Weak<MainWindow>, outcome: worker::SettingsOutcome) {
    SETTINGS_MODEL.with(|slot| {
        if let Some(model) = slot.borrow().as_ref() {
            let items: Vec<SettingItem> = outcome
                .snapshot
                .rows
                .iter()
                .map(|r| SettingItem {
                    key: r.key.clone().into(),
                    name: r.name.clone().into(),
                    value: r.value.clone().into(),
                    status: r.status.clone().into(),
                    editor: r.editor.clone().into(),
                    options: r.options.join("; ").into(),
                    group: r.group.into(),
                })
                .collect();
            model.set_vec(items);
        }
    });

    if !outcome.snapshot.dirty {
        // Load or successful save: the pending set is fully incorporated.
        PENDING_SETTINGS.with(|slot| slot.borrow_mut().clear());
    }

    if let Some(w) = ui.upgrade() {
        w.set_settings_valid(outcome.snapshot.validation_ok);
        w.set_settings_validation_text(outcome.snapshot.validation_message.clone().into());
        w.set_settings_dirty(outcome.snapshot.dirty);
        if !outcome.message.is_empty() {
            w.set_settings_message(outcome.message.clone().into());
            set_status(&w, &outcome.message);
        }
        if outcome.gamertag_recomputed {
            GAMERTAG.with(|slot| *slot.borrow_mut() = outcome.config.gamertag.clone());
            w.set_context_gamertag(outcome.config.gamertag.clone().into());
            w.set_run_info(run_info_line(&outcome.config).into());
            set_status(&w, "gamertag changed; best laps recomputed");
            send_request(Request::ListBestLaps);
            send_request(Request::ListReviews {
                bucket: "open".into(),
            });
            send_request(Request::RefreshInventory {
                filter: ImageInventoryFilter::default(),
            });
        }
    }
    RUN_CONFIG.with(|slot| {
        *slot.borrow_mut() = Some(forza_app::RunParams::from_config(&outcome.config, false));
    });
}

thread_local! {
    static WORKER_TX: std::cell::OnceCell<mpsc::Sender<Request>> =
        const { std::cell::OnceCell::new() };
}

fn send_request(request: Request) {
    WORKER_TX.with(|slot| {
        if let Some(tx) = slot.get() {
            let _ = tx.send(request);
        }
    });
}

fn enqueue(request: Request, ui: &slint::Weak<MainWindow>, loading: &str) {
    WORKER_TX.with(|slot| {
        if let Some(tx) = slot.get()
            && tx.send(request).is_err()
            && let Some(w) = ui.upgrade()
        {
            set_status(&w, "error: worker stopped");
        }
    });
    if let Some(w) = ui.upgrade() {
        set_status(&w, loading);
    }
}
