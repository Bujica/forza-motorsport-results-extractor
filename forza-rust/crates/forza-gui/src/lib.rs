//! forza-gui: Slint front-end of the Rust line (Fase 4 slice + F10 pages).
//!
//! Threading contract (migration plan §4.9): the Tokio runtime lives on a
//! dedicated worker thread; Slint callbacks are synchronous and only enqueue
//! typed requests; results come back to the UI thread through
//! `slint::invoke_from_event_loop`. Widget-adjacent state (`Rc` models, row
//! cache) lives in UI-thread locals and is never shared across threads.

pub mod detail_views;
pub mod ui_state;
pub mod worker;

use detail_views::{
    apply_debug_cases, apply_debug_detail, apply_image_detail, apply_settings, step_detail,
};
use ui_state::{
    BESTLAP_ALL, BESTLAP_FILTER, BESTLAP_MODEL, BESTLAP_SORT, CONFIG_PATH, DEBUG_CASE_MODEL,
    DEBUG_CASES_CACHE, DEBUG_DETAIL_CACHE, DEBUG_RESULT_MODEL, DETAIL_ATTEMPT_MODEL, DETAIL_INDEX,
    DETAIL_LAP_MODEL, DETAIL_RESULT_MODEL, DETAIL_REVIEW_MODEL, GAMERTAG, LIST_MODEL,
    PENDING_SETTINGS, REVIEW_MODEL, ROW_CACHE, RUN_CONFIG, RUN_CONTROL, RUN_LOG, RUN_SELECTED_IDS,
    RUN_START, SELECTED_IMAGE_IDS, SETTINGS_LOADED, SETTINGS_MODEL, WORKER_TX, append_run_log,
    compute_rate_eta, enqueue, image_items, run_info_line, send_request, set_status,
    update_image_selection,
};

use std::cell::RefCell;
use std::path::{Path, PathBuf};
use std::rc::Rc;
use std::sync::mpsc;

use slint::{ModelRc, VecModel};

use crate::worker::{Request, Response, WorkerContext};
use forza_app::{ImageInventoryEntry, ImageInventoryFilter, ReviewQueueFilter};

slint::include_modules!();

thread_local! {
    /// Anchor row for Shift+click range selection.
    static SELECTION_ANCHOR: std::cell::RefCell<usize> = const { std::cell::RefCell::new(0) };
    /// (column index, ascending)
    static SORT_STATE: std::cell::RefCell<(usize, bool)> = const { std::cell::RefCell::new((0, true)) };
}

fn current_inventory_filter() -> ImageInventoryFilter {
    ImageInventoryFilter::default()
}

/// Re-sort the cached rows per SORT_STATE and refresh the visible model and
/// the header arrows.
fn apply_inventory_sort(ui: &MainWindow) {
    let (column, ascending) = SORT_STATE.with(|slot| *slot.borrow());
    ui.set_sort_column(column as i32);
    ui.set_sort_ascending(ascending);
    ROW_CACHE.with(|rows| {
        let mut rows = rows.borrow_mut();
        let key = |e: &ImageInventoryEntry| match column {
            0 => (e.name.to_lowercase(), String::new()),
            1 => (
                e.race_date.clone().unwrap_or_default(),
                e.name.to_lowercase(),
            ),
            2 => (
                e.semantic_name.clone().unwrap_or_default(),
                e.name.to_lowercase(),
            ),
            3 => (e.file_status.clone(), e.name.to_lowercase()),
            4 => (e.duplicate_label.clone(), e.name.to_lowercase()),
            5 => (e.processing_status.clone(), e.name.to_lowercase()),
            _ => (e.best_lap_status.clone(), e.name.to_lowercase()),
        };
        rows.sort_by(|a, b| {
            let (ka, kb) = (key(a), key(b));
            if ascending { ka.cmp(&kb) } else { kb.cmp(&ka) }
        });
    });
    ROW_CACHE.with(|rows| {
        let rows = rows.borrow().clone();
        LIST_MODEL.with(|slot| {
            if let Some(model) = slot.borrow().as_ref() {
                model.set_vec(image_items(&rows));
            }
        });
    });
}

/// Python-style multi-selection summary line.
fn update_selection_summary(ui: &MainWindow) {
    let (count, missing, duplicates, unprocessed, skipped, errors) =
        SELECTED_IMAGE_IDS.with(|selected| {
            let selected = selected.borrow();
            let mut missing = 0;
            let mut duplicates = 0;
            let mut unprocessed = 0;
            let mut skipped = 0;
            let mut errors = 0;
            ROW_CACHE.with(|rows| {
                for entry in rows.borrow().iter() {
                    if !selected.contains(&entry.id) {
                        continue;
                    }
                    if entry.file_status == "missing" {
                        missing += 1;
                    }
                    if entry.duplicate_label == "Duplicate" {
                        duplicates += 1;
                    }
                    match entry.processing_status.as_str() {
                        "unprocessed" => unprocessed += 1,
                        "skipped" => skipped += 1,
                        "processed_error" => errors += 1,
                        _ => {}
                    }
                }
            });
            (
                selected.len(),
                missing,
                duplicates,
                unprocessed,
                skipped,
                errors,
            )
        });
    if count == 0 {
        ui.set_selection_summary(slint::SharedString::new());
        return;
    }
    ui.set_selection_summary(
        format!(
            "Selected {count} \u{b7} Missing {missing} \u{b7} Duplicates {duplicates} \u{b7} Unprocessed {unprocessed} \u{b7} Skipped {skipped} \u{b7} Errors {errors}"
        )
        .into(),
    );
}

#[allow(dead_code)]
fn class_color(class: &str) -> &'static str {
    match class {
        "E" => "#C7368E",
        "D" => "#127F85",
        "C" => "#BB7A00",
        "B" => "#C54E00",
        "A" => "#992800",
        "TCR" => "#1E90FF",
        "S" => "#613BBF",
        "R" => "#105DAB",
        "P" => "#0C8540",
        "X" => "#006000",
        "Mixed" => "#555555",
        _ => "#000000",
    }
}

fn apply_bestlaps_filters(ui: &MainWindow) {
    let gamertag_lower = GAMERTAG.with(|s| s.borrow().clone().to_lowercase());
    let (all_rows, filter, sort) = (
        BESTLAP_ALL.with(|s| s.borrow().clone()),
        BESTLAP_FILTER.with(|s| s.borrow().clone()),
        BESTLAP_SORT.with(|s| *s.borrow()),
    );
    let mut filtered = forza_app::apply_filters(&all_rows, &filter, &gamertag_lower, None);
    // Domain ordering (Python): track canonical -> class -> weather -> time -> driver -> car
    // Header sort overrides it only when user explicitly clicks a column; default (99) keeps domain order.
    let track_order = forza_domain::reference_data::embedded_reference_data().tracks;
    let order_map = forza_domain::ordering::track_order_map(&track_order);
    if sort.0 <= 3 {
        filtered.sort_by(|a, b| {
            let ord = match sort.0 {
                0 => a.driver.to_lowercase().cmp(&b.driver.to_lowercase()),
                1 => a.car.to_lowercase().cmp(&b.car.to_lowercase()),
                2 => a.best_lap_ms.cmp(&b.best_lap_ms),
                3 => a.weather.to_lowercase().cmp(&b.weather.to_lowercase()),
                _ => std::cmp::Ordering::Equal,
            };
            let ord = if ord == std::cmp::Ordering::Equal {
                forza_domain::ordering::ordered_lap_key(a, &order_map)
                    .cmp(&forza_domain::ordering::ordered_lap_key(b, &order_map))
            } else {
                ord
            };
            if sort.1 { ord } else { ord.reverse() }
        });
    } else {
        // Default: preserve Python's ordered_lap_key ordering (all_rows already sorted, but re-sort to guarantee stability after filters).
        filtered.sort_by_key(|a| forza_domain::ordering::ordered_lap_key(a, &order_map));
    }
    let summary = forza_app::summary(&filtered, filter.only_mine);
    ui.set_best_laps_summary(forza_app::summary_text(&summary, filter.only_mine).into());
    ui.set_best_laps_sort_column(sort.0 as i32);
    ui.set_best_laps_sort_ascending(sort.1);
    // Filter option models (cascade: exclude self)
    let options = forza_app::filter_options(&all_rows, &filter, &gamertag_lower);
    let to_model = |values: Vec<String>| -> ModelRc<slint::SharedString> {
        let mut with_all = vec!["all".into()];
        with_all.extend(values.into_iter().map(|v| v.into()));
        ModelRc::from(Rc::new(VecModel::from(with_all)))
    };
    ui.set_best_laps_tracks(to_model(options.tracks));
    ui.set_best_laps_classes(to_model(options.race_classes));
    ui.set_best_laps_weathers(to_model(options.weather));
    ui.set_best_laps_drivers(to_model(options.drivers));
    ui.set_best_laps_cars(to_model(options.cars));
    ui.set_best_laps_sources({
        let mut vals = options.source_states;
        if vals.is_empty() {
            vals = vec!["screenshots".to_string(), "external".to_string()];
        }
        let mut with_all = vec!["all".into()];
        with_all.extend(vals.into_iter().map(|v| v.into()));
        ModelRc::from(Rc::new(VecModel::from(with_all)))
    });
    ui.set_best_laps_laps({
        let mut vals = options.dirty_states;
        if vals.is_empty() {
            vals = vec!["clean".to_string(), "dirty".to_string()];
        }
        let mut with_all = vec!["all".into()];
        with_all.extend(vals.into_iter().map(|v| v.into()));
        ModelRc::from(Rc::new(VecModel::from(with_all)))
    });
    // Build grouped display list: group header + rows.
    let mut counts: std::collections::HashMap<(String, String), usize> =
        std::collections::HashMap::new();
    for r in &filtered {
        *counts
            .entry((r.track.clone(), r.race_class.clone()))
            .or_insert(0) += 1;
    }
    let mut items: Vec<BestLapItem> = Vec::new();
    let mut current_key: Option<(String, String)> = None;
    for r in &filtered {
        let key = (r.track.clone(), r.race_class.clone());
        if current_key.as_ref() != Some(&key) {
            let cnt = *counts.get(&key).unwrap_or(&0) as i32;
            items.push(BestLapItem {
                track: r.track.clone().into(),
                class: r.race_class.clone().into(),
                driver: "".into(),
                car: "".into(),
                time: "".into(),
                weather: "".into(),
                temp: "".into(),
                source: "".into(),
                dirty: false,
                mine: false,
                external: false,
                is_group: true,
                group_count: cnt,
            });
            current_key = Some(key);
        }
        let is_mine = !gamertag_lower.is_empty() && r.driver.to_lowercase() == gamertag_lower;
        items.push(BestLapItem {
            track: r.track.clone().into(),
            class: r.race_class.clone().into(),
            driver: r.driver.clone().into(),
            car: r.car.clone().into(),
            time: r.best_lap.clone().into(),
            weather: r.weather.clone().into(),
            temp: r
                .temp_c
                .map(|v| format!("{v:.0}°C"))
                .unwrap_or_default()
                .into(),
            source: if r.is_external {
                r.source_label.clone().into()
            } else {
                "screenshots".into()
            },
            dirty: r.dirty,
            mine: is_mine,
            external: r.is_external,
            is_group: false,
            group_count: 0,
        });
    }
    BESTLAP_MODEL.with(|slot| {
        if let Some(model) = slot.borrow().as_ref() {
            model.set_vec(items);
        }
    });
}

thread_local! {
    /// Currently listed review cases (source of truth for details/actions).
    static REVIEW_CASES_CACHE: RefCell<Vec<forza_app::ReviewCaseEntry>> =
        const { RefCell::new(Vec::new()) };
    /// Active review filter (set by the filter bar, reused on reload).
    static REVIEW_FILTER: RefCell<ReviewQueueFilter> = RefCell::new(ReviewQueueFilter {
        bucket: String::from("open"),
        ..Default::default()
    });
    /// Selected review case position (isize: -1 = none).
    static REVIEW_INDEX: RefCell<isize> = const { RefCell::new(-1) };
    /// Reference tracks offered on the track-correction combo.
    static REVIEW_TRACKS: RefCell<Vec<String>> = const { RefCell::new(Vec::new()) };
}

fn set_review_track_model(main: &MainWindow, values: Vec<slint::SharedString>) {
    main.set_review_tracks(ModelRc::from(Rc::new(VecModel::from(values))));
}

fn set_review_class_model(main: &MainWindow, values: Vec<slint::SharedString>) {
    main.set_review_classes(ModelRc::from(Rc::new(VecModel::from(values))));
}

/// Build the details-panel text for the selected review case (Python
/// details grid labels) and refresh the reason/suggestion hints.
fn apply_review_detail(ui: &MainWindow) {
    let case = REVIEW_INDEX.with(|slot| *slot.borrow());
    let entry = REVIEW_CASES_CACHE.with(|slot| {
        let cache = slot.borrow();
        if case >= 0 && (case as usize) < cache.len() {
            Some(cache[case as usize].clone())
        } else {
            None
        }
    });

    match entry {
        Some(c) => {
            ui.set_review_detail_title(format!("Case #{}", c.case_number).into());
            let temp = c
                .temp_f
                .map(|t| format!("{t:.1} °F"))
                .unwrap_or_else(|| "-".to_string());
            ui.set_review_detail_lines(
                format!(
                    "Case: {}\nOutcome: {}\nReason: {}\nTrigger: {}\nModel value: {}\nCorrected value: {}\nDecision: {}\nError: {}\nFile: {}\nCurrent track: {}\nCurrent class: {}\nCurrent weather: {}\nTemp: {}\nCurrent driver: {}\nCurrent lap: {}",
                    c.case_number,
                    c.outcome.clone().unwrap_or_default(),
                    c.reason,
                    c.trigger.clone().unwrap_or_default(),
                    c.model_value.clone().unwrap_or_default(),
                    c.corrected_value.clone().unwrap_or_default(),
                    c.decision_field.clone().unwrap_or_default(),
                    c.error_type.clone().unwrap_or_default(),
                    c.source_file.clone().unwrap_or_default(),
                    c.track.clone().unwrap_or_default(),
                    c.race_class.clone().unwrap_or_default(),
                    c.weather.clone().unwrap_or_default(),
                    temp,
                    c.driver.clone().unwrap_or_default(),
                    c.best_lap.clone().unwrap_or_default(),
                )
                .into(),
            );
            ui.set_review_reason_note(c.reason.clone().into());
            ui.set_review_suggestions(String::new().into());
            if let Some(image_file_id) = c.image_file_id.clone() {
                send_request(Request::LoadPreview { image_file_id });
            } else {
                ui.set_review_has_preview(false);
            }
        }
        None => {
            ui.set_review_detail_title("Review queue is clear.".into());
            ui.set_review_detail_lines(String::new().into());
            ui.set_review_reason_note(String::new().into());
            ui.set_review_suggestions(String::new().into());
            ui.set_review_has_preview(false);
        }
    }
}

/// Open the image detail page at a given inventory row index.
fn open_image_detail_at(ui: &slint::Weak<MainWindow>, index: i32) {
    if let Some(w) = ui.upgrade() {
        w.set_page("image-detail".into());
        w.set_detail_loaded(false);
        w.invoke_open_image_detail(index);
    }
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
                    options,
                    filter_label,
                } => match result {
                    Ok(entries) => {
                        let count = entries.len();
                        ROW_CACHE.with(|slot| *slot.borrow_mut() = entries.clone());
                        LIST_MODEL.with(|slot| {
                            if let Some(model) = slot.borrow().as_ref() {
                                SELECTED_IMAGE_IDS.with(|selected| {
                                    selected
                                        .borrow_mut()
                                        .retain(|id| entries.iter().any(|e| &e.id == id));
                                });
                                model.set_vec(image_items(&entries));
                            }
                        });
                        if let Some(w) = ui.upgrade() {
                            apply_inventory_sort(&w);
                            update_image_selection(&w);
                            update_selection_summary(&w);
                            w.set_status_text(format!("{count} image(s) [{filter_label}]").into());
                        }
                        if let Ok(options) = options
                            && let Some(w) = ui.upgrade()
                            && w.get_image_track_filter() == "all"
                            && w.get_image_run_filter() == "all"
                        {
                            let tracks: Vec<slint::SharedString> = std::iter::once("all".into())
                                .chain(options.tracks.into_iter().map(Into::into))
                                .collect();
                            let runs: Vec<slint::SharedString> = std::iter::once("all".into())
                                .chain(options.runs.into_iter().map(Into::into))
                                .collect();
                            w.set_image_tracks(ModelRc::from(Rc::new(VecModel::from(tracks))));
                            w.set_image_runs(ModelRc::from(Rc::new(VecModel::from(runs))));
                        }
                    }
                    Err(message) => {
                        if let Some(w) = ui.upgrade() {
                            w.set_status_text(format!("error: {message}").into());
                        }
                    }
                },
                Response::Reviews {
                    result,
                    options,
                    filter,
                } => match &result {
                    Ok(entries) => {
                        REVIEW_CASES_CACHE.with(|slot| *slot.borrow_mut() = entries.clone());
                        REVIEW_MODEL.with(|slot| {
                            if let Some(model) = slot.borrow().as_ref() {
                                let items: Vec<ReviewItem> = entries
                                    .iter()
                                    .map(|c| ReviewItem {
                                        number: c.case_number as i32,
                                        outcome: c.outcome.clone().unwrap_or_default().into(),
                                        reason: c.reason.clone().into(),
                                        trigger: c.trigger.clone().unwrap_or_default().into(),
                                        decision: match (
                                            c.decision_field.as_deref(),
                                            c.model_value.as_deref(),
                                            c.corrected_value.as_deref(),
                                        ) {
                                            (Some(field), Some(model_value), Some(corrected)) => {
                                                format!("{field}: {model_value} -> {corrected}")
                                            }
                                            (Some(field), Some(model_value), None) => {
                                                format!("{field}: {model_value}")
                                            }
                                            _ => String::new(),
                                        }
                                        .into(),
                                        driver: c.driver.clone().unwrap_or_default().into(),
                                        lap: if c.best_lap.clone().unwrap_or_default().is_empty() {
                                            String::new()
                                        } else if c.status == "open" {
                                            format!(
                                                "{} dirty",
                                                c.best_lap.clone().unwrap_or_default()
                                            )
                                        } else {
                                            c.best_lap.clone().unwrap_or_default()
                                        }
                                        .into(),
                                        lap_dirty: c.status == "open"
                                            && !c.best_lap.clone().unwrap_or_default().is_empty(),
                                        status: c.status.clone().into(),
                                        image_file_id: c
                                            .image_file_id
                                            .clone()
                                            .unwrap_or_default()
                                            .into(),
                                    })
                                    .collect();
                                model.set_vec(items);
                            }
                        });
                        let options_model = |values: &[String]| -> ModelRc<slint::SharedString> {
                            ModelRc::from(Rc::new(VecModel::from(
                                std::iter::once("all".to_string())
                                    .chain(values.iter().cloned())
                                    .map(Into::into)
                                    .collect::<Vec<_>>(),
                            )))
                        };
                        if let Some(w) = ui.upgrade() {
                            w.set_review_reasons(options_model(&options.reasons));
                            w.set_review_outcomes(options_model(&options.outcomes));
                            w.set_review_runs(options_model(&options.runs));
                            w.set_review_selected_index(if entries.is_empty() { -1 } else { 0 });
                            apply_review_detail(&w);
                            w.set_status_text(
                                format!("{} review case(s) [{}]", entries.len(), filter.bucket)
                                    .into(),
                            );
                        }
                    }
                    Err(message) => {
                        REVIEW_CASES_CACHE.with(|slot| slot.borrow_mut().clear());
                        if let Some(w) = ui.upgrade() {
                            w.set_status_text(format!("error: {message}").into());
                        }
                    }
                },
                Response::Preview(result) => match result {
                    Ok(Some(path)) => {
                        if let Some(w) = ui.upgrade() {
                            let loaded = slint::Image::load_from_path(Path::new(&path)).ok();
                            w.set_review_has_preview(loaded.is_some());
                            w.set_review_preview(loaded.unwrap_or_default());
                        }
                    }
                    Ok(None) => {
                        if let Some(w) = ui.upgrade() {
                            w.set_review_has_preview(false);
                        }
                    }
                    Err(message) => {
                        if let Some(w) = ui.upgrade() {
                            set_status(&w, &format!("preview error: {message}"));
                        }
                    }
                },
                Response::CaseReopen(result) => {
                    if let (Err(message), Some(w)) = (&result, ui.upgrade()) {
                        set_status(&w, &format!("error: {message}"));
                    }
                    let filter = REVIEW_FILTER.with(|slot| slot.borrow().clone());
                    send_request(Request::ListReviews { filter });
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
                            filter: ReviewQueueFilter {
                                bucket: "open".into(),
                                ..Default::default()
                            },
                        });
                        send_request(Request::ListBestLaps);
                    }
                }
                Response::BestLaps(result) => {
                    match result {
                        Ok(rows) => {
                            BESTLAP_ALL.with(|slot| *slot.borrow_mut() = rows);
                            // Ensure filter defaults are "all" when fresh.
                            BESTLAP_FILTER.with(|slot| {
                                let mut f = slot.borrow_mut();
                                if f.dirty.is_empty() {
                                    f.dirty = "all".to_string();
                                }
                                if f.source.is_empty() {
                                    f.source = "all".to_string();
                                }
                            });
                            if let Some(w) = ui.upgrade() {
                                apply_bestlaps_filters(&w);
                                let count = BESTLAP_ALL.with(|s| s.borrow().len());
                                w.set_status_text(format!("{count} best lap(s) loaded").into());
                            }
                        }
                        Err(message) => {
                            if let Some(w) = ui.upgrade() {
                                w.set_status_text(format!("error: {message}").into());
                            }
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
                        filter: ReviewQueueFilter {
                            bucket: String::from("all"),
                            ..Default::default()
                        },
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
                Response::ExportDone(result) => match result {
                    Ok((exported, skipped)) => {
                        if let Some(w) = ui.upgrade() {
                            set_status(
                                &w,
                                &format!("exported {exported} image(s), skipped {skipped}"),
                            );
                        }
                    }
                    Err(message) => {
                        if let Some(w) = ui.upgrade() {
                            set_status(&w, &format!("export failed: {message}"));
                        }
                    }
                },
                Response::RescanDone(result) => match result {
                    Ok((available, missing)) => {
                        if let Some(w) = ui.upgrade() {
                            set_status(
                                &w,
                                &format!(
                                    "rescan: {available} back available, {missing} now missing"
                                ),
                            );
                        }
                        send_request(Request::RefreshInventory {
                            filter: ImageInventoryFilter::default(),
                        });
                    }
                    Err(message) => {
                        if let Some(w) = ui.upgrade() {
                            set_status(&w, &format!("rescan failed: {message}"));
                        }
                    }
                },
                Response::DeleteDone(result) => match result {
                    Ok((deleted, refused, sample)) => {
                        if let Some(w) = ui.upgrade() {
                            set_status(
                                &w,
                                &format!("deleted {deleted} image(s); refused {refused} {sample}"),
                            );
                        }
                        send_request(Request::RefreshInventory {
                            filter: ImageInventoryFilter::default(),
                        });
                    }
                    Err(message) => {
                        if let Some(w) = ui.upgrade() {
                            set_status(&w, &format!("delete failed: {message}"));
                        }
                    }
                },
                Response::RenameDone(result) => {
                    if let Some(w) = ui.upgrade() {
                        match result {
                            Ok(message) => {
                                set_status(&w, &message);
                                send_request(Request::RefreshInventory {
                                    filter: ImageInventoryFilter::default(),
                                });
                            }
                            Err(message) => {
                                set_status(&w, format!("rename error: {message}").as_str())
                            }
                        }
                    }
                }
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
                Response::ImageDebugCases(result) => {
                    apply_debug_cases(&ui, result);
                }
                Response::ImageDebugDetail(result) => match result {
                    Ok(Some(detail)) => apply_debug_detail(&ui, detail),
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
                Response::Logs(result) => match result {
                    Ok((app_log, error_log)) => {
                        if let Some(w) = ui.upgrade() {
                            w.set_app_log_text(app_log.into());
                            w.set_error_log_text(error_log.into());
                            w.set_status_text("logs loaded".into());
                        }
                    }
                    Err(message) => {
                        if let Some(w) = ui.upgrade() {
                            set_status(&w, format!("error: {message}").as_str());
                        }
                    }
                },
                Response::ImportDone(result) => match result {
                    Ok(info) => {
                        if let Some(w) = ui.upgrade() {
                            w.set_status_text(info.message().into());
                        }
                        send_request(Request::ListBestLaps);
                    }
                    Err(message) => {
                        if let Some(w) = ui.upgrade() {
                            w.set_status_text(format!("import failed: {message}").into());
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
        main.on_refresh_requested(
            move |file_value,
                  best_value,
                  inventory_value,
                  track_value,
                  run_value,
                  process_value| {
                let filter = ImageInventoryFilter {
                    file_status: (file_value != "all").then(|| file_value.to_string()),
                    best_lap_status: (best_value != "all").then(|| best_value.to_string()),
                    inventory_filter: (inventory_value != "all")
                        .then(|| inventory_value.to_string()),
                    track: (track_value != "all").then(|| track_value.to_string()),
                    run_id: (run_value != "all").then(|| run_value.to_string()),
                    processing_status: (process_value != "all").then(|| process_value.to_string()),
                    ..Default::default()
                };
                enqueue(
                    Request::RefreshInventory { filter },
                    &ui,
                    &format!("loading images ({process_value})…"),
                );
            },
        );
    }
    {
        let ui = main.as_weak();
        main.on_selection_toggle(move |index| {
            SELECTION_ANCHOR.with(|slot| *slot.borrow_mut() = index as usize);
            let id = ROW_CACHE.with(|rows| rows.borrow().get(index as usize).map(|e| e.id.clone()));
            if let Some(id) = id {
                SELECTED_IMAGE_IDS.with(|selected| {
                    let mut selected = selected.borrow_mut();
                    if let Some(pos) = selected.iter().position(|item| item == &id) {
                        selected.remove(pos);
                    } else {
                        selected.push(id);
                    }
                });
                if let Some(w) = ui.upgrade() {
                    update_image_selection(&w);
                    update_selection_summary(&w);
                }
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_clear_selection(move || {
            SELECTED_IMAGE_IDS.with(|selected| selected.borrow_mut().clear());
            if let Some(w) = ui.upgrade() {
                update_image_selection(&w);
                update_selection_summary(&w);
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_selection_single(move |index| {
            SELECTION_ANCHOR.with(|slot| *slot.borrow_mut() = index as usize);
            let id = ROW_CACHE.with(|rows| rows.borrow().get(index as usize).map(|e| e.id.clone()));
            if let Some(id) = id {
                SELECTED_IMAGE_IDS.with(|selected| {
                    *selected.borrow_mut() = vec![id];
                });
                if let Some(w) = ui.upgrade() {
                    update_image_selection(&w);
                    update_selection_summary(&w);
                }
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_selection_range(move |end| {
            let (ids, anchor) = ROW_CACHE.with(|rows| {
                let rows = rows.borrow();
                let anchor = SELECTION_ANCHOR.with(|slot| *slot.borrow());
                let (lo, hi) = if anchor <= end as usize {
                    (anchor, end as usize + 1)
                } else {
                    (end as usize + 1, anchor + 1)
                };
                let ids: Vec<String> = rows
                    .get(lo..hi.min(rows.len()))
                    .map(|slice| slice.iter().map(|e| e.id.clone()).collect())
                    .unwrap_or_default();
                (ids, anchor)
            });
            let _ = anchor;
            SELECTED_IMAGE_IDS.with(|selected| *selected.borrow_mut() = ids);
            if let Some(w) = ui.upgrade() {
                update_image_selection(&w);
                update_selection_summary(&w);
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_select_all(move || {
            let ids = ROW_CACHE.with(|rows| {
                rows.borrow()
                    .iter()
                    .map(|e| e.id.clone())
                    .collect::<Vec<_>>()
            });
            SELECTED_IMAGE_IDS.with(|selected| *selected.borrow_mut() = ids);
            if let Some(w) = ui.upgrade() {
                update_image_selection(&w);
                update_selection_summary(&w);
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_sort_changed(move |column| {
            SORT_STATE.with(|slot| {
                let mut state = slot.borrow_mut();
                let (current_col, current_asc) = *state;
                let ascending = if current_col == column as usize {
                    !current_asc
                } else {
                    true
                };
                *state = (column as usize, ascending);
            });
            if let Some(w) = ui.upgrade() {
                apply_inventory_sort(&w);
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_scan_folder(move || {
            if let Some(w) = ui.upgrade() {
                set_status(&w, "Syncing input folder...");
            }
            let ui = ui.clone();
            let filter = current_inventory_filter();
            send_request(Request::RefreshInventory { filter });
            let _ = ui;
        });
    }
    {
        let ui = main.as_weak();
        main.on_export_selected(move || {
            let ids = SELECTED_IMAGE_IDS.with(|slot| slot.borrow().clone());
            if ids.is_empty() {
                return;
            }
            let Some(dest_dir) = rfd::FileDialog::new()
                .set_title("Choose export destination")
                .pick_folder()
            else {
                return;
            };
            send_request(Request::ExportImages {
                image_ids: ids,
                dest_dir: dest_dir.to_string_lossy().to_string(),
            });
            if let Some(w) = ui.upgrade() {
                set_status(&w, "Exporting selected images...");
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_rescan_selected(move || {
            let ids = SELECTED_IMAGE_IDS.with(|slot| slot.borrow().clone());
            if ids.is_empty() {
                return;
            }
            send_request(Request::RescanImages { image_ids: ids });
            if let Some(w) = ui.upgrade() {
                set_status(&w, "Rescanning selected images...");
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_delete_selected(move || {
            let ids = SELECTED_IMAGE_IDS.with(|slot| slot.borrow().clone());
            if ids.is_empty() {
                return;
            }
            send_request(Request::DeleteImages { image_ids: ids });
            if let Some(w) = ui.upgrade() {
                set_status(&w, "Deleting selected images...");
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_process_selected(move || {
            let selected = SELECTED_IMAGE_IDS.with(|ids| ids.borrow().clone());
            if selected.is_empty() {
                return;
            }
            RUN_SELECTED_IDS.with(|slot| *slot.borrow_mut() = Some(selected));
            if let Some(w) = ui.upgrade() {
                w.invoke_start_run(false, w.get_force_checked(), w.get_retry_checked());
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_rename_selected(move || {
            let selected = SELECTED_IMAGE_IDS.with(|ids| ids.borrow().clone());
            if selected.is_empty() {
                return;
            }
            enqueue(
                Request::RenameImages {
                    image_ids: selected,
                },
                &ui,
                "renaming selected images…",
            );
        });
    }
    {
        let ui = main.as_weak();
        main.on_selection_changed(move |index| {
            let image_id = ROW_CACHE.with(|rows| {
                rows.borrow()
                    .get(index as usize)
                    .map(|entry| entry.id.clone())
            });
            ROW_CACHE.with(|rows| {
                let guard = rows.borrow();
                let Some(entry) = guard.get(index as usize) else { return };
                if let Some(w) = ui.upgrade() {
                    w.set_detail_has_preview(false);
                    w.set_detail_title(entry.name.clone().into());
                    w.set_detail_lines(
                        format!(
                            "id: {}\nfile_status: {}\nbest_lap_status: {}\nprocessing: {}\nsize: {}\nhash: {}\nsemantic: {}\npath: {}\nduplicate: {}",
                            entry.id,
                            entry.file_status,
                            entry.best_lap_status,
                            entry.processing_status,
                            entry
                                .size_bytes
                                .map(|b| format!("{b} bytes"))
                                .unwrap_or_else(|| "-".into()),
                            entry.file_hash,
                            entry.semantic_name.clone().unwrap_or_default(),
                            entry.current_path.clone().unwrap_or_default(),
                            entry.duplicate_label,
                        )
                        .into(),
                    );
                }
            });
            if let Some(image_id) = image_id {
                send_request(Request::LoadImageDetail { image_id });
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_reviews_requested(move || {
            let filter = REVIEW_FILTER.with(|slot| slot.borrow().clone());
            enqueue(Request::ListReviews { filter }, &ui, "loading reviews…");
        });
    }
    {
        let ui = main.as_weak();
        main.on_review_filter_changed(move |status, reason, outcome, run| {
            REVIEW_FILTER.with(|slot| {
                *slot.borrow_mut() = ReviewQueueFilter {
                    bucket: status.to_string(),
                    reason: Some(reason.to_string()),
                    outcome: Some(outcome.to_string()),
                    run_id: Some(run.to_string()),
                    image_file_id: None,
                };
            });
            let filter = REVIEW_FILTER.with(|slot| slot.borrow().clone());
            enqueue(Request::ListReviews { filter }, &ui, "loading reviews…");
        });
    }
    {
        let ui = main.as_weak();
        main.on_review_selected(move |index| {
            REVIEW_INDEX.with(|slot| *slot.borrow_mut() = index as isize);
            if let Some(w) = ui.upgrade() {
                apply_review_detail(&w);
            }
            let preview_id = REVIEW_CASES_CACHE.with(|slot| {
                slot.borrow()
                    .get(index as usize)
                    .and_then(|c| c.image_file_id.clone())
            });
            if let Some(image_id) = preview_id {
                send_request(Request::LoadPreview {
                    image_file_id: image_id,
                });
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_review_apply(move |case_number, field, value| {
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
        main.on_review_ignore(move |case_number| {
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
        main.on_review_reopen(move |case_number| {
            enqueue(
                Request::ReopenCase {
                    case_number: case_number as i64,
                },
                &ui,
                "reopening case…",
            );
        });
    }
    {
        let ui = main.as_weak();
        main.on_review_open_detail(move |case_number| {
            let index = REVIEW_CASES_CACHE.with(|slot| {
                slot.borrow()
                    .iter()
                    .position(|c| c.case_number == case_number as i64)
                    .map(|p| p as i32)
                    .unwrap_or(-1)
            });
            if index >= 0 {
                let ui2 = ui.clone();
                open_image_detail_at(&ui2, index);
            }
        });
    }
    {
        main.on_review_preview_requested(move |image_file_id| {
            send_request(Request::LoadPreview {
                image_file_id: image_file_id.to_string(),
            });
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
        main.on_bestlaps_filter_changed(
            move |track, class, weather, driver, car, lap, source, only_mine| {
                BESTLAP_FILTER.with(|slot| {
                    *slot.borrow_mut() = forza_app::BestLapFilter::from_strings(
                        &track, &class, &weather, &driver, &car, &lap, &source, only_mine,
                    );
                });
                if let Some(w) = ui.upgrade() {
                    apply_bestlaps_filters(&w);
                }
            },
        );
    }
    {
        let ui = main.as_weak();
        main.on_bestlaps_sort_changed(move |col| {
            BESTLAP_SORT.with(|slot| {
                let mut state = slot.borrow_mut();
                let (cur_col, cur_asc) = *state;
                let asc = if cur_col == col as usize {
                    !cur_asc
                } else {
                    true
                };
                *state = (col as usize, asc);
            });
            if let Some(w) = ui.upgrade() {
                apply_bestlaps_filters(&w);
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_bestlaps_export_csv(move || {
            let Some(dest) = rfd::FileDialog::new()
                .set_title("Export best laps")
                .add_filter("CSV", &["csv"])
                .set_file_name("best_laps.csv")
                .save_file()
            else {
                return;
            };
            let rows = BESTLAP_ALL.with(|all| {
                let filter = BESTLAP_FILTER.with(|f| f.borrow().clone());
                let gamertag = GAMERTAG.with(|s| s.borrow().clone().to_lowercase());
                forza_app::apply_filters(&all.borrow(), &filter, &gamertag, None)
            });
            if rows.is_empty() {
                if let Some(w) = ui.upgrade() {
                    w.set_status_text("No best laps to export.".into());
                }
                return;
            }
            let export_rows = forza_app::to_export_rows(&rows);
            let result = forza_output::export_csv(&export_rows, &dest);
            if let Some(w) = ui.upgrade() {
                match result {
                    Ok(n) => w.set_status_text(
                        format!("Best laps exported: {n} row(s) · {}", dest.display()).into(),
                    ),
                    Err(e) => w.set_status_text(format!("Export failed: {e}").into()),
                }
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_bestlaps_generate_pdf(move || {
            let rows = BESTLAP_ALL.with(|all| {
                let filter = BESTLAP_FILTER.with(|f| f.borrow().clone());
                let gamertag = GAMERTAG.with(|s| s.borrow().clone().to_lowercase());
                forza_app::apply_filters(&all.borrow(), &filter, &gamertag, None)
            });
            if rows.is_empty() {
                if let Some(w) = ui.upgrade() {
                    w.set_status_text("No filtered best laps to generate PDF.".into());
                }
                return;
            }
            let config_path = CONFIG_PATH.with(|p| p.borrow().clone());
            let (cfg, _) = match forza_config::load_config(&config_path, false) {
                Ok(v) => v,
                Err(e) => {
                    if let Some(w) = ui.upgrade() {
                        w.set_status_text(format!("Config load failed: {}", e.message).into());
                    }
                    return;
                }
            };
            // Track order from embedded reference data (matches Python's reference catalog).
            let track_order: Vec<String> = forza_domain::reference_data::embedded_reference_data()
                .tracks
                .into_iter()
                .collect();
            let internal = rows
                .iter()
                .filter(|r| !r.is_external)
                .cloned()
                .collect::<Vec<_>>();
            let external = rows
                .iter()
                .filter(|r| r.is_external)
                .cloned()
                .collect::<Vec<_>>();
            let internal_export = forza_app::to_export_rows(&internal);
            let external_records = external
                .iter()
                .map(|r| forza_output::PdfExternalRecord {
                    track: r.track.clone(),
                    race_class: r.race_class.clone(),
                    driver: r.driver.clone(),
                    car: r.car.clone(),
                    best_lap: forza_domain::lap::strip_dirty_symbol(&r.best_lap),
                    best_lap_ms: r.best_lap_ms,
                })
                .collect::<Vec<_>>();
            let options = forza_output::PdfRenderOptions {
                show_dirty_symbol: cfg.pdf.show_dirty_lap_symbol,
                dirty_symbol: cfg.pdf.dirty_lap_symbol.clone(),
            };
            let plan = forza_output::build_pdf_plan_ext(
                &internal_export,
                &cfg.gamertag,
                &track_order,
                &external_records,
                options,
            );
            let pdf_path = config_path
                .parent()
                .unwrap_or_else(|| Path::new("."))
                .join(&cfg.pdf_file);
            match forza_output::render_pdf(&plan, &pdf_path) {
                Ok(_) => {
                    if let Some(w) = ui.upgrade() {
                        w.set_status_text(
                            format!(
                                "Filtered PDF generated: {} row(s) · {}",
                                rows.len(),
                                pdf_path.display()
                            )
                            .into(),
                        );
                    }
                    let _ = opener::open(&pdf_path);
                }
                Err(e) => {
                    if let Some(w) = ui.upgrade() {
                        w.set_status_text(format!("PDF generation failed: {e}").into());
                    }
                }
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_bestlaps_open_pdf(move || {
            let config_path = CONFIG_PATH.with(|p| p.borrow().clone());
            let (cfg, _) = match forza_config::load_config(&config_path, false) {
                Ok(v) => v,
                Err(e) => {
                    if let Some(w) = ui.upgrade() {
                        w.set_status_text(format!("Config load failed: {}", e.message).into());
                    }
                    return;
                }
            };
            let pdf_path = config_path
                .parent()
                .unwrap_or_else(|| Path::new("."))
                .join(&cfg.pdf_file);
            if !pdf_path.exists() {
                if let Some(w) = ui.upgrade() {
                    w.set_status_text(format!("PDF not found: {}", pdf_path.display()).into());
                }
                return;
            }
            let _ = opener::open(&pdf_path);
            if let Some(w) = ui.upgrade() {
                w.set_status_text(format!("Opened PDF: {}", pdf_path.display()).into());
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_bestlaps_import(move || {
            let Some(path) = rfd::FileDialog::new()
                .set_title("Import external records")
                .add_filter("Spreadsheets", &["xlsx", "csv"])
                .pick_file()
            else {
                return;
            };
            enqueue(
                Request::ImportExternalRecords {
                    path: path.to_string_lossy().to_string(),
                },
                &ui,
                "importing external records…",
            );
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
            // Lazy settings/debug/logs loads on first entry (GUI state rules).
            if page == "settings" && !SETTINGS_LOADED.with(|slot| *slot.borrow()) {
                SETTINGS_LOADED.with(|slot| *slot.borrow_mut() = true);
                send_request(Request::LoadSettings);
            }
            if page == "image-debug" {
                send_request(Request::ListImageDebugCases {
                    filter: forza_app::ImageDebugFilter::default(),
                });
            }
            if page == "logs" {
                send_request(Request::LoadLogs);
            }
            if page == "best-laps" {
                send_request(Request::ListBestLaps);
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
    {
        let ui = main.as_weak();
        main.on_debug_refresh_requested(move || {
            enqueue(
                Request::ListImageDebugCases {
                    filter: forza_app::ImageDebugFilter::default(),
                },
                &ui,
                "loading debug cases…",
            );
        });
    }
    {
        let ui = main.as_weak();
        main.on_debug_case_selected(move |index| {
            let id = DEBUG_CASES_CACHE.with(|c| {
                c.borrow()
                    .get(index as usize)
                    .map(|case| case.image_file_id.clone())
            });
            let Some(id) = id else { return };
            enqueue(
                Request::LoadImageDebugDetail {
                    image_file_id: id,
                    selected_result_id: None,
                },
                &ui,
                "loading debug detail…",
            );
        });
    }
    {
        let ui = main.as_weak();
        main.on_debug_result_selected(move |result_id| {
            let image_id = DEBUG_DETAIL_CACHE
                .with(|c| c.borrow().as_ref().map(|d| d.image_file_id.clone()))
                .unwrap_or_default();
            if image_id.is_empty() {
                return;
            }
            enqueue(
                Request::LoadImageDebugDetail {
                    image_file_id: image_id,
                    selected_result_id: Some(result_id.to_string()),
                },
                &ui,
                "loading result detail…",
            );
        });
    }
    {
        let ui = main.as_weak();
        main.on_open_image_debug(move |image_file_id| {
            if let Some(w) = ui.upgrade() {
                w.set_page("image-debug".into());
            }
            enqueue(
                Request::LoadImageDebugDetail {
                    image_file_id: image_file_id.to_string(),
                    selected_result_id: None,
                },
                &ui,
                "opening image debug…",
            );
        });
    }
    {
        let ui = main.as_weak();
        main.on_debug_open_image_detail(move || {
            let image_id = DEBUG_DETAIL_CACHE
                .with(|c| c.borrow().as_ref().map(|d| d.image_file_id.clone()))
                .unwrap_or_default();
            if image_id.is_empty() {
                return;
            }
            // Navigate to Image Detail page.
            if let Some(w) = ui.upgrade() {
                w.set_page("image-detail".into());
            }
            enqueue(
                Request::LoadImageDetail { image_id },
                &ui,
                "loading image detail…",
            );
        });
    }
    {
        let ui = main.as_weak();
        main.on_logs_reload_requested(move || {
            enqueue(Request::LoadLogs, &ui, "reloading logs…");
        });
    }

    // ── Live extraction runner (own thread, cooperative cancel) ──────────
    {
        let ui = main.as_weak();
        main.on_start_run(move |dry_run, force, retry| {
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
            let already_running = RUN_CONTROL.with(|slot| slot.borrow().is_some());
            if already_running {
                if let Some(w) = ui.upgrade() {
                    set_status(&w, "a run is already active");
                }
                return;
            }
            let Some(params) = RUN_CONFIG.with(|slot| slot.borrow().clone()) else { return };
            let params = forza_app::RunParams {
                force,
                retry_errors: retry && !force,
                selected_image_file_ids: RUN_SELECTED_IDS.with(|slot| slot.borrow_mut().take()),
                ..params
            };
            let control = forza_app::RunControl::new();
            RUN_CONTROL.with(|slot| *slot.borrow_mut() = Some(control.clone()));
            if let Some(w) = ui.upgrade() {
                w.set_run_running(true);
                w.set_run_paused(false);
                w.set_run_done(0);
                w.set_run_total(0);
                w.set_run_percent(0.0);
            }
            append_run_log(format!(
                "[start] {} model={} force={} retry_errors={}",
                forza_app::APP_VERSION, params.model, params.force, params.retry_errors
            ));

            let ui = ui.clone();
            let _handle = forza_app::spawn_extraction(params, control, move |event| {
                let ui = ui.clone();
                let _ = slint::invoke_from_event_loop(move || match event {
                    forza_app::RunEvent::Started { run_id, total } => {
                        append_run_log(format!("[run {run_id}] {total} file(s) considered"));
                        RUN_START.with(|slot| {
                            *slot.borrow_mut() = Some(std::time::Instant::now());
                        });
                        if let Some(w) = ui.upgrade() {
                            w.set_run_total(total as i32);
                            w.set_run_rate("".into());
                            w.set_run_eta("".into());
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
                            let (rate, eta) = RUN_START.with(|slot| {
                                compute_rate_eta(done as i32, total as i32, *slot.borrow())
                            });
                            w.set_run_rate(rate.into());
                            w.set_run_eta(eta.into());
                        }
                    }
                    forza_app::RunEvent::Log(line) => append_run_log(line),
                    forza_app::RunEvent::Finished { cancelled, processed, succeeded, failed, elapsed_s } => {
                        append_run_log(format!(
                            "[done] cancelled={cancelled} processed={processed} ok={succeeded} fail={failed} in {elapsed_s:.1}s"
                        ));
                        RUN_CONTROL.with(|slot| *slot.borrow_mut() = None);
                        RUN_START.with(|slot| *slot.borrow_mut() = None);
                        if let Some(w) = ui.upgrade() {
                            w.set_run_running(false);
                            w.set_run_paused(false);
                            w.set_run_percent(100.0);
                        }
                        // Refresh derived views after a run.
                        send_request(Request::RefreshInventory {
                            filter: ImageInventoryFilter::default(),
                        });
                        send_request(Request::ListBestLaps);
                        send_request(Request::ListReviews { filter: ReviewQueueFilter { bucket: String::from("open"), ..Default::default() } });
                    }
                    forza_app::RunEvent::Failed(message) => {
                        append_run_log(format!("[failed] {message}"));
                        RUN_CONTROL.with(|slot| *slot.borrow_mut() = None);
                        RUN_START.with(|slot| *slot.borrow_mut() = None);
                        if let Some(w) = ui.upgrade() {
                            w.set_run_running(false);
                            w.set_run_paused(false);
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
            RUN_CONTROL.with(|slot| {
                if let Some(control) = slot.borrow().as_ref() {
                    control.request_cancel();
                    if let Some(w) = ui.upgrade() {
                        w.set_run_paused(false);
                        set_status(&w, "cancellation requested…");
                    }
                }
            });
        });
    }
    {
        let ui = main.as_weak();
        main.on_toggle_pause(move || {
            RUN_CONTROL.with(|slot| {
                if let Some(control) = slot.borrow().as_ref() {
                    let resuming = control.is_paused();
                    control
                        .paused
                        .store(!resuming, std::sync::atomic::Ordering::Relaxed);
                    if let Some(w) = ui.upgrade() {
                        w.set_run_paused(!resuming);
                        set_status(&w, if resuming { "resumed" } else { "paused" });
                    }
                    append_run_log(if resuming { "[resumed]" } else { "[paused]" }.to_string());
                }
            });
        });
    }

    // Review page reference data (track correction combo + class list).
    {
        let refs = forza_domain::reference_data::embedded_reference_data();
        let mut tracks: Vec<slint::SharedString> =
            refs.tracks.iter().cloned().map(Into::into).collect();
        tracks.sort_by_key(|t| t.to_lowercase());
        set_review_track_model(&main, tracks);
        let classes: Vec<slint::SharedString> = [
            "E", "D", "C", "B", "A", "TCR", "S", "R", "P", "X", "Mixed", "Unknown",
        ]
        .iter()
        .map(|c| c.to_string().into())
        .collect();
        set_review_class_model(&main, classes);
    }

    // Initial load.
    main.set_status_text("loading…".into());
    send_request(Request::RefreshInventory {
        filter: ImageInventoryFilter::default(),
    });
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
