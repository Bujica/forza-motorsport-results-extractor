//! forza-gui: Slint front-end of the Rust line (Fase 4 slice + F10 pages).
//!
//! Threading contract (migration plan §4.9): the Tokio runtime lives on a
//! dedicated worker thread; Slint callbacks are synchronous and only enqueue
//! typed requests; results come back to the UI thread through
//! `slint::invoke_from_event_loop`. Widget-adjacent state (`Rc` models, row
//! cache) lives in UI-thread locals and is never shared across threads.

pub mod worker;

use std::cell::RefCell;
use std::path::{Path, PathBuf};
use std::rc::Rc;
use std::sync::mpsc;

use slint::{ModelRc, VecModel};

use crate::worker::{Request, Response};
use forza_app::{ImageInventoryEntry, ImageInventoryFilter};

slint::include_modules!();

thread_local! {
    static LIST_MODEL: RefCell<Option<Rc<VecModel<ImageItem>>>> = const { RefCell::new(None) };
    static ROW_CACHE: RefCell<Vec<ImageInventoryEntry>> = const { RefCell::new(Vec::new()) };
    static REVIEW_MODEL: RefCell<Option<Rc<VecModel<ReviewItem>>>> = const { RefCell::new(None) };
    static BESTLAP_MODEL: RefCell<Option<Rc<VecModel<BestLapItem>>>> = const { RefCell::new(None) };
    static GAMERTAG: RefCell<String> = const { RefCell::new(String::new()) };
}

fn set_status(ui: &MainWindow, text: &str) {
    ui.set_status_text(text.into());
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

    // Context header values.
    main.set_context_db(db_path.display().to_string().into());
    main.set_context_gamertag(cfg.gamertag.clone().into());

    // Worker thread owns the receiver; responses marshal back to this loop.
    let (tx, rx) = mpsc::channel::<Request>();
    {
        let ui = main.as_weak();
        worker::spawn_thread(rx, db_path.clone(), cfg.gamertag.clone(), move |response| {
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
