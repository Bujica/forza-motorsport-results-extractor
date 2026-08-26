//! forza-gui: Slint front-end of the Rust line (Fase 4 vertical slice).
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
    /// Backing store of the images list (UI thread only).
    static LIST_MODEL: RefCell<Option<Rc<VecModel<ImageItem>>>> = const { RefCell::new(None) };
    /// Rows backing the list so the detail pane resolves selections without
    /// another query (UI thread only).
    static ROW_CACHE: RefCell<Vec<ImageInventoryEntry>> = const { RefCell::new(Vec::new()) };
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
    let model = Rc::new(VecModel::<ImageItem>::from(Vec::new()));
    main.set_images(ModelRc::from(model.clone()));
    LIST_MODEL.with(|slot| *slot.borrow_mut() = Some(model.clone()));

    // Worker thread owns the receiver; responses marshal back to this loop.
    let (tx, rx) = mpsc::channel::<Request>();
    {
        let ui = main.as_weak();
        worker::spawn_thread(rx, db_path.clone(), move |response| {
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
            });
        });
    }

    // Filters / refresh button -> enqueue request.
    {
        let tx = tx.clone();
        let ui = main.as_weak();
        main.on_refresh_requested(move |filter_value| {
            let filter = ImageInventoryFilter {
                processing_status: (filter_value != "all").then(|| filter_value.to_string()),
                ..Default::default()
            };
            if tx.send(Request::RefreshInventory { filter }).is_err()
                && let Some(w) = ui.upgrade()
            {
                w.set_status_text("error: worker stopped".into());
            }
            if let Some(w) = ui.upgrade() {
                w.set_status_text(format!("loading ({filter_value})…").into());
            }
        });
    }

    // Selection -> detail pane from already-loaded rows (no extra query).
    {
        let ui = main.as_weak();
        main.on_selection_changed(move |index| {
            ROW_CACHE.with(|slot| {
                let guard = slot.borrow();
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

    // Initial load.
    main.set_status_text("loading…".into());
    let _ = tx.send(Request::RefreshInventory {
        filter: ImageInventoryFilter::default(),
    });

    main.run()?;
    drop(tx);
    Ok(())
}
