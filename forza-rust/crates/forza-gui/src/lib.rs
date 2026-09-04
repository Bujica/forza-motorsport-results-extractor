//! forza-gui: Slint front-end of the Rust line (Fase 4 slice + F10 pages).
//!
//! Threading contract (migration plan §4.9): the Tokio runtime lives on a
//! dedicated worker thread; Slint callbacks are synchronous and only enqueue
//! typed requests; results come back to the UI thread through
//! `slint::invoke_from_event_loop`. Widget-adjacent state (`Rc` models, row
//! cache) lives in UI-thread locals and is never shared across threads.

pub mod detail_views;
pub mod ui_persist;
pub mod ui_state;
pub mod worker;

use detail_views::{
    apply_debug_cases, apply_debug_detail, apply_image_detail, apply_settings, step_detail,
};
use ui_state::{
    BESTLAP_ALL, BESTLAP_FILTER, BESTLAP_MODEL, BESTLAP_SORT, CONFIG_PATH, DEBUG_CASE_MODEL,
    DEBUG_CASES_CACHE, DEBUG_DETAIL_CACHE, DEBUG_RESULT_MODEL, DETAIL_ATTEMPT_MODEL, DETAIL_INDEX,
    DETAIL_LAP_MODEL, DETAIL_RESULT_MODEL, DETAIL_REVIEW_MODEL, GAMERTAG, LIST_MODEL, LOGS_APP_RAW,
    LOGS_ERROR_RAW, PENDING_IMPORT_MESSAGE, PENDING_SETTINGS, REVIEW_MODEL, ROW_CACHE, RUN_CONFIG,
    RUN_CONTROL, RUN_LOG, RUN_SELECTED_IDS, RUN_START, SELECTED_IMAGE_IDS, SETTINGS_LOADED,
    SETTINGS_MODEL, WORKER_TX, append_run_log, compute_rate_eta, enqueue, image_items,
    run_info_line, send_request, set_status, update_image_selection,
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
    /// Coalesce rapid filter changes like Python's _refresh_pending_args.
    static INVENTORY_REFRESH_IN_FLIGHT: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
    static PENDING_INVENTORY_FILTER: std::cell::RefCell<Option<ImageInventoryFilter>> =
        const { std::cell::RefCell::new(None) };
    /// Last inventory filter actually issued, so background refreshes
    /// (post-decision, rescan, rebuild) don't clobber the user's filter bar
    /// with defaults.
    static CURRENT_INVENTORY_FILTER: std::cell::RefCell<ImageInventoryFilter> =
        const { std::cell::RefCell::new(ImageInventoryFilter {
            file_status: None,
            best_lap_status: None,
            inventory_filter: None,
            track: None,
            run_id: None,
            processing_status: None,
            include_missing_files: false,
        }) };
    static REVIEW_REFRESH_IN_FLIGHT: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
    static PENDING_REVIEW_FILTER: std::cell::RefCell<Option<ReviewQueueFilter>> =
        const { std::cell::RefCell::new(None) };
    /// Monotonic id for settings previews: preview jobs run concurrently, so
    /// an older response arriving last must be dropped instead of restoring
    /// stale rows over newer edits.
    static SETTINGS_PREVIEW_SEQ: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
}

pub(crate) fn current_inventory_filter() -> ImageInventoryFilter {
    CURRENT_INVENTORY_FILTER.with(|s| s.borrow().clone())
}

fn remember_inventory_filter(filter: &ImageInventoryFilter) {
    CURRENT_INVENTORY_FILTER.with(|s| *s.borrow_mut() = filter.clone());
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
                image_file_id: "".into(),
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
                .temp_f
                .map(|v| format!("{v:.0}°F"))
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
            image_file_id: r.image_file_id.clone().unwrap_or_default().into(),
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
            let decision = match (&c.decision_field, &c.corrected_value) {
                (Some(d), Some(cv)) if !d.is_empty() => {
                    let before = c.model_value.as_deref().unwrap_or("?");
                    format!("{d}: {before} -> {cv}")
                }
                _ => "—".to_string(),
            };
            let current_driver = c.driver.clone().unwrap_or_default();
            let current_car = c.car.clone().unwrap_or_default();
            let current_lap = c.best_lap.clone().unwrap_or_default();
            ui.set_review_detail_lines(
                format!(
                    "Case: {}\nStable ID: {}\nOutcome: {}\nReason: {}\nTrigger: {}\nModel value: {}\nCorrected value: {}\nDecision: {}\nError: {}\nResolution: {}\nFile: {}\nCurrent track: {}\nCurrent class: {}\nCurrent weather: {}\nTemp: {}\nCurrent driver: {}\nCurrent car: {}\nCurrent lap: {}",
                    c.case_number,
                    c.image_file_id.clone().unwrap_or_default(),
                    c.outcome.clone().unwrap_or_default(),
                    c.reason,
                    c.trigger.clone().unwrap_or_default(),
                    c.model_value.clone().unwrap_or_default(),
                    c.corrected_value.clone().unwrap_or_default(),
                    decision,
                    c.error_type.clone().unwrap_or_default(),
                    c.resolution_note.clone().unwrap_or_default(),
                    c.source_file.clone().unwrap_or_default(),
                    c.track.clone().unwrap_or_default(),
                    c.race_class.clone().unwrap_or_default(),
                    c.weather.clone().unwrap_or_default(),
                    temp,
                    current_driver,
                    current_car,
                    current_lap,
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

/// Open image detail directly by image id (used by the Review page: the
/// review queue and the inventory are different lists, so a review-cache
/// position must never be reused as an inventory index).
fn open_image_detail_by_id(ui: &slint::Weak<MainWindow>, image_id: &str) {
    let index = ROW_CACHE.with(|rows| {
        rows.borrow()
            .iter()
            .position(|e| e.id == image_id)
            .map(|p| p as i32)
            .unwrap_or(-1)
    });
    if index >= 0 {
        open_image_detail_at(ui, index);
        return;
    }
    // Not in the current inventory window: request detail directly.
    DETAIL_INDEX.with(|slot| *slot.borrow_mut() = -1);
    if let Some(w) = ui.upgrade() {
        w.set_page("image-detail".into());
        w.set_detail_loaded(false);
        set_status(&w, "loading image detail…");
    }
    send_request(Request::LoadImageDetail {
        image_id: image_id.to_string(),
    });
}

/// Primary display work area in physical px (0 when unknown).
#[cfg(windows)]
fn primary_screen_px() -> (i32, i32) {
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        GetSystemMetrics, SM_CXFULLSCREEN, SM_CYFULLSCREEN,
    };
    // Trivial win32 query; no invariants to uphold.
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

/// Launch the GUI. Blocks until the window closes.
pub fn run(config_path: &Path) -> anyhow::Result<()> {
    let (mut cfg, warnings) = forza_config::load_config(config_path, false)?;
    for warning in warnings {
        eprintln!("config warning: {warning}");
    }
    forza_config::validate_config(&cfg)
        .map_err(|errors| anyhow::anyhow!("configuration invalid: {}", errors.join("; ")))?;

    // Robust DB path: `load_config` already resolves relative to the ini file,
    // but when the GUI is launched from `target/debug` the ini there points to
    // `target/debug/data/forza.sqlite3` (4.9 MB) while the Python CLI uses
    // `data/forza.sqlite3` at the workspace root (15 MB, 693 images). Try
    // workspace candidates so both front-ends share the same DB.
    let mut db_path: PathBuf = cfg.database_file.clone();
    if !db_path.exists() {
        let candidates: Vec<PathBuf> = {
            let mut v = Vec::new();
            // Relative to cwd
            v.push(PathBuf::from("data/forza.sqlite3"));
            v.push(PathBuf::from("../data/forza.sqlite3"));
            v.push(PathBuf::from("../../data/forza.sqlite3"));
            // Relative to ini file
            if let Some(dir) = config_path.parent() {
                v.push(dir.join("data/forza.sqlite3"));
                v.push(dir.join("../data/forza.sqlite3"));
                v.push(dir.join("../../data/forza.sqlite3"));
            }
            // Walk up from exe location
            if let Ok(exe) = std::env::current_exe() {
                let mut cur = exe.parent().map(Path::to_path_buf).unwrap_or_default();
                for _ in 0..5 {
                    v.push(cur.join("data/forza.sqlite3"));
                    v.push(cur.join("../data/forza.sqlite3"));
                    if let Some(p) = cur.parent() {
                        cur = p.to_path_buf();
                    } else {
                        break;
                    }
                }
            }
            v
        };
        for cand in candidates {
            if cand.exists() {
                db_path = cand;
                cfg.database_file = db_path.clone();
                break;
            }
        }
    } else {
        // Even if the configured path exists, prefer the workspace DB when the
        // configured one is the tiny `target/debug/data` copy and the workspace
        // one is larger (Python parity). This keeps the GUI and CLI in sync.
        let workspace_cand = PathBuf::from("data/forza.sqlite3");
        // Only switch if the workspace DB exists and is larger
        if workspace_cand.exists()
            && db_path
                .canonicalize()
                .ok()
                .and_then(|p| {
                    p.parent().map(|d| {
                        d.ends_with("target/debug/data") || d.ends_with("target\\debug\\data")
                    })
                })
                .unwrap_or(false)
        {
            if let Ok(ws_meta) = std::fs::metadata(&workspace_cand) {
                if let Ok(cur_meta) = std::fs::metadata(&db_path) {
                    if ws_meta.len() > cur_meta.len() {
                        db_path = workspace_cand
                            .canonicalize()
                            .unwrap_or(workspace_cand.clone());
                        cfg.database_file = db_path.clone();
                    }
                }
            }
        }
    }
    if !db_path.exists() {
        return Err(anyhow::anyhow!(
            "database {} does not exist; run `forza maintenance db-upgrade` first",
            db_path.display()
        ));
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
                } => {
                    match result {
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
                                w.set_selected_index(-1);
                                w.set_scan_status("".into());
                                w.set_status_text(
                                    format!("{count} image(s) [{filter_label}]").into(),
                                );
                            }
                            if let Ok(options) = options
                                && let Some(w) = ui.upgrade()
                                && w.get_image_track_filter() == "all"
                                && w.get_image_run_filter() == "all"
                            {
                                let tracks: Vec<slint::SharedString> =
                                    std::iter::once("all".into())
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
                    }
                    INVENTORY_REFRESH_IN_FLIGHT.with(|f| f.set(false));
                    if let Some(pending) =
                        PENDING_INVENTORY_FILTER.with(|slot| slot.borrow_mut().take())
                    {
                        INVENTORY_REFRESH_IN_FLIGHT.with(|f| f.set(true));
                        let ui2 = ui.clone();
                        enqueue(
                            Request::RefreshInventory { filter: pending },
                            &ui2,
                            "loading images…",
                        );
                    }
                }
                Response::Reviews {
                    result,
                    options,
                    filter,
                } => {
                    match &result {
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
                                                (
                                                    Some(field),
                                                    Some(model_value),
                                                    Some(corrected),
                                                ) => {
                                                    format!("{field}: {model_value} -> {corrected}")
                                                }
                                                (Some(field), Some(model_value), None) => {
                                                    format!("{field}: {model_value}")
                                                }
                                                _ => String::new(),
                                            }
                                            .into(),
                                            driver: c.driver.clone().unwrap_or_default().into(),
                                            lap: if c
                                                .best_lap
                                                .clone()
                                                .unwrap_or_default()
                                                .is_empty()
                                            {
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
                                                && !c
                                                    .best_lap
                                                    .clone()
                                                    .unwrap_or_default()
                                                    .is_empty(),
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
                            let options_model =
                                |values: &[String]| -> ModelRc<slint::SharedString> {
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
                                // The option models were just replaced: a stale
                                // combo index past the new length would read as
                                // "" and silently drop that filter dimension.
                                // Clamp back to "all" (index 0) so the bar and
                                // the active filter agree.
                                let clamp = |current: i32, len: usize| -> i32 {
                                    if current >= 0 && (current as usize) < len {
                                        current
                                    } else {
                                        0
                                    }
                                };
                                w.set_review_reason_index(clamp(
                                    w.get_review_reason_index(),
                                    options.reasons.len() + 1,
                                ));
                                w.set_review_outcome_index(clamp(
                                    w.get_review_outcome_index(),
                                    options.outcomes.len() + 1,
                                ));
                                w.set_review_run_index(clamp(
                                    w.get_review_run_index(),
                                    options.runs.len() + 1,
                                ));
                                // Auto-advance: keep current index if still valid, else clamp to 0; -1 if empty (F5)
                                let cur = REVIEW_INDEX.with(|s| *s.borrow());
                                let next_idx = if entries.is_empty() {
                                    -1
                                } else if cur >= 0 && (cur as usize) < entries.len() {
                                    cur as i32
                                } else {
                                    0
                                };
                                w.set_review_selected_index(next_idx);
                                REVIEW_INDEX.with(|s| *s.borrow_mut() = next_idx as isize);
                                apply_review_detail(&w);
                                w.set_status_text(
                                    format!("{} review case(s) [{}]", entries.len(), filter.bucket)
                                        .into(),
                                );
                            }
                        }
                        Err(message) => {
                            // Clear the cache AND the visible model together:
                            // leaving stale rows on screen while apply/ignore
                            // operate against an emptied cache is a desync.
                            REVIEW_CASES_CACHE.with(|slot| slot.borrow_mut().clear());
                            REVIEW_MODEL.with(|slot| {
                                if let Some(model) = slot.borrow().as_ref() {
                                    model.set_vec(Vec::new());
                                }
                            });
                            REVIEW_INDEX.with(|s| *s.borrow_mut() = -1);
                            if let Some(w) = ui.upgrade() {
                                w.set_review_selected_index(-1);
                                w.set_status_text(format!("error: {message}").into());
                                apply_review_detail(&w);
                            }
                        }
                    }
                    REVIEW_REFRESH_IN_FLIGHT.with(|f| f.set(false));
                    if let Some(pending) =
                        PENDING_REVIEW_FILTER.with(|slot| slot.borrow_mut().take())
                    {
                        REVIEW_REFRESH_IN_FLIGHT.with(|f| f.set(true));
                        let ui2 = ui.clone();
                        enqueue(
                            Request::ListReviews { filter: pending },
                            &ui2,
                            "loading reviews…",
                        );
                    }
                }
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
                        // Auto-advance within filtered queue (F5): reload with current filter, preserve index
                        let filter = REVIEW_FILTER.with(|s| s.borrow().clone());
                        // Advance index to next case before reload (same index now points to next after removal)
                        REVIEW_INDEX.with(|s| {
                            let cur = *s.borrow();
                            let len = REVIEW_CASES_CACHE.with(|c| c.borrow().len());
                            if len > 0 && cur >= 0 && (cur as usize) < len {
                                // keep same index (next case shifts into place)
                            } else if cur >= len as isize {
                                *s.borrow_mut() = (len as isize - 1).max(0);
                            }
                        });
                        send_request(Request::ListReviews { filter });
                        send_request(Request::ListBestLaps);
                        // A decision can change best-lap/processing columns, so
                        // refresh the inventory too with the user's current
                        // filter (never forced defaults).
                        send_request(Request::RefreshInventory {
                            filter: current_inventory_filter(),
                        });
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
                                let pending =
                                    PENDING_IMPORT_MESSAGE.with(|s| s.borrow_mut().take());
                                if let Some(msg) = pending {
                                    w.set_status_text(msg.into());
                                } else {
                                    let count = BESTLAP_ALL.with(|s| s.borrow().len());
                                    w.set_status_text(format!("{count} best lap(s) loaded").into());
                                }
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
                                w.set_doctor_report(summary.summary_text.clone().into());
                                w.set_doctor_overall(summary.overall.clone().into());
                                w.set_doctor_summary(summary.summary_text.clone().into());
                                let items: Vec<DoctorCheckItem> = summary
                                    .checks
                                    .into_iter()
                                    .map(|c| DoctorCheckItem {
                                        result: c.result.into(),
                                        count: c.count.to_string().into(),
                                        check: c.key.into(),
                                        description: c.detail.into(),
                                    })
                                    .collect();
                                let cnt = items.len();
                                w.set_doctor_checks(ModelRc::from(Rc::new(VecModel::from(items))));
                                w.set_status_text(
                                    format!("doctor: {} · {} checks", summary.overall, cnt).into(),
                                );
                            }
                            Err(message) => {
                                w.set_doctor_report(format!("error: {message}").into());
                                w.set_doctor_overall("FAIL".into());
                                w.set_doctor_summary(message.into());
                                w.set_doctor_checks(ModelRc::from(Rc::new(VecModel::from(Vec::<
                                    DoctorCheckItem,
                                >::new(
                                )))));
                            }
                        }
                    }
                }
                Response::Overview(result) => {
                    if let Some(w) = ui.upgrade() {
                        match result {
                            Ok(s) => {
                                w.set_overview_lm_level(s.lm_level.clone().into());
                                w.set_overview_lm_message(s.lm_message.clone().into());
                                w.set_overview_endpoint(s.lm_endpoint.clone().into());
                                w.set_overview_model(s.lm_model.clone().into());
                                w.set_overview_loaded_instance(s.lm_loaded_instance.clone().into());
                                w.set_overview_configured_load(s.lm_configured_load.clone().into());
                                w.set_overview_configured_request(
                                    s.lm_configured_request.clone().into(),
                                );
                                w.set_overview_configured_image(
                                    s.lm_configured_image.clone().into(),
                                );
                                w.set_overview_runtime_policy(s.lm_runtime_policy.clone().into());
                                w.set_overview_loaded_runtime(s.lm_loaded_runtime.clone().into());
                                w.set_overview_capabilities(s.lm_capabilities.clone().into());
                                w.set_overview_model_info(s.lm_model_info.clone().into());
                                w.set_overview_warnings(s.lm_warnings.clone().into());
                                w.set_overview_db_status(
                                    if s.db_ok {
                                        "ok".into()
                                    } else {
                                        format!("{} error(s)", s.db_errors)
                                    }
                                    .into(),
                                );
                                w.set_overview_schema(s.schema_state.clone().into());
                                w.set_overview_inventory(
                                    format!("{}/{} available", s.available_images, s.images).into(),
                                );
                                w.set_overview_review(format!("{} open", s.review_open).into());
                                w.set_doctor_report(
                                    format!("db: {} · schema {}", s.schema_state, s.db_errors)
                                        .into(),
                                );
                                w.set_status_text("overview refreshed".into());
                            }
                            Err(message) => {
                                w.set_status_text(format!("overview error: {message}").into())
                            }
                        }
                    }
                }
                Response::ClearLogs(result) => {
                    if let Some(w) = ui.upgrade() {
                        match result {
                            Ok(msg) => {
                                w.set_status_text(msg.into());
                                send_request(Request::LoadLogs);
                            }
                            Err(message) => {
                                w.set_status_text(format!("clear failed: {message}").into())
                            }
                        }
                    }
                }
                Response::OpenLogFolder(result) => {
                    if let Some(w) = ui.upgrade() {
                        match result {
                            Ok(msg) => w.set_status_text(msg.into()),
                            Err(message) => {
                                w.set_status_text(format!("open folder failed: {message}").into())
                            }
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
                                    "rebuild: {} winner(s); reviews +{} kept {} auto-resolved {} (flags +{}/{})",
                                    outcome.best_lap_winners,
                                    outcome.review_inserted,
                                    outcome.review_kept,
                                    outcome.review_auto_resolved,
                                    outcome.flags_ensured,
                                    outcome.flags_resolved
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
                        INVENTORY_REFRESH_IN_FLIGHT.with(|f| f.set(true));
                        send_request(Request::RefreshInventory {
                            filter: current_inventory_filter(),
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
                        INVENTORY_REFRESH_IN_FLIGHT.with(|f| f.set(true));
                        send_request(Request::RefreshInventory {
                            filter: current_inventory_filter(),
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
                                INVENTORY_REFRESH_IN_FLIGHT.with(|f| f.set(true));
                                send_request(Request::RefreshInventory {
                                    filter: current_inventory_filter(),
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
                        // Drop stale previews (seq 0 = load/save, always applied).
                        let latest = SETTINGS_PREVIEW_SEQ.with(|s| s.get());
                        if outcome.seq != 0 && outcome.seq != latest {
                            return;
                        }
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
                        LOGS_APP_RAW.with(|s| *s.borrow_mut() = app_log.clone());
                        LOGS_ERROR_RAW.with(|s| *s.borrow_mut() = error_log.clone());
                        if let Some(w) = ui.upgrade() {
                            // Apply current search filter if any
                            let search = w.get_logs_search().to_string().to_lowercase();
                            let filter = |text: &str| -> String {
                                if search.is_empty() {
                                    text.to_string()
                                } else {
                                    text.lines()
                                        .filter(|l| l.to_lowercase().contains(&search))
                                        .collect::<Vec<_>>()
                                        .join("\n")
                                }
                            };
                            let app_filtered = filter(&app_log);
                            let err_filtered = filter(&error_log);
                            // Store filtered view; keep raw for re-filtering
                            w.set_app_log_text(app_filtered.clone().into());
                            w.set_error_log_text(err_filtered.clone().into());
                            let shown = if w.get_logs_tab() == "app" {
                                &app_filtered
                            } else {
                                &err_filtered
                            };
                            let count = if search.is_empty() {
                                "".to_string()
                            } else {
                                format!("{} matching line(s)", shown.lines().count())
                            };
                            w.set_logs_status(count.into());
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
                        let msg = info.message();
                        PENDING_IMPORT_MESSAGE.with(|s| *s.borrow_mut() = Some(msg));
                        send_request(Request::ListBestLaps);
                    }
                    Err(message) => {
                        if let Some(w) = ui.upgrade() {
                            w.set_status_text(format!("import failed: {message}").into());
                        }
                    }
                },
                Response::Error(message) => {
                    // A job thread panicked: release the coalescing flags so
                    // later filter changes issue fresh requests instead of
                    // parking behind "loading…" forever.
                    INVENTORY_REFRESH_IN_FLIGHT.with(|f| f.set(false));
                    REVIEW_REFRESH_IN_FLIGHT.with(|f| f.set(false));
                    if let Some(w) = ui.upgrade() {
                        w.set_status_text(format!("error: {message}").into());
                    }
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
                // Coalesce rapid changes like Python's ImageController._refresh_pending_args
                PENDING_INVENTORY_FILTER.with(|slot| *slot.borrow_mut() = Some(filter.clone()));
                if INVENTORY_REFRESH_IN_FLIGHT.with(|f| f.get()) {
                    return;
                }
                INVENTORY_REFRESH_IN_FLIGHT.with(|f| f.set(true));
                // Clear pending because we're about to process this exact filter
                PENDING_INVENTORY_FILTER.with(|slot| *slot.borrow_mut() = None);
                remember_inventory_filter(&filter);
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
                w.set_scan_status("Syncing input folder...".into());
            }
            let filter = current_inventory_filter();
            INVENTORY_REFRESH_IN_FLIGHT.with(|f| f.set(true));
            enqueue(
                Request::SyncInputFolder { filter },
                &ui,
                "syncing input folder…",
            );
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
            // Don't stash the selection before knowing the run will start:
            // if a run is already active `on_start_run` returns early and the
            // stale `RUN_SELECTED_IDS` would leak into the next plain Run All.
            let already_running = RUN_CONTROL.with(|slot| slot.borrow().is_some());
            if already_running {
                if let Some(w) = ui.upgrade() {
                    set_status(&w, "a run is already active");
                }
                return;
            }
            let selected = SELECTED_IMAGE_IDS.with(|ids| ids.borrow().clone());
            if selected.is_empty() {
                return;
            }
            RUN_SELECTED_IDS.with(|slot| *slot.borrow_mut() = Some(selected));
            if let Some(w) = ui.upgrade() {
                w.invoke_start_run(
                    false,
                    w.get_force_checked(),
                    w.get_retry_checked(),
                    w.get_debug_checked(),
                );
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_select_in_images(move || {
            if let Some(w) = ui.upgrade() {
                w.set_page("images".into());
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
            PENDING_REVIEW_FILTER.with(|slot| *slot.borrow_mut() = Some(filter.clone()));
            if REVIEW_REFRESH_IN_FLIGHT.with(|f| f.get()) {
                return;
            }
            REVIEW_REFRESH_IN_FLIGHT.with(|f| f.set(true));
            PENDING_REVIEW_FILTER.with(|slot| *slot.borrow_mut() = None);
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
            PENDING_REVIEW_FILTER.with(|slot| *slot.borrow_mut() = Some(filter.clone()));
            if REVIEW_REFRESH_IN_FLIGHT.with(|f| f.get()) {
                return;
            }
            REVIEW_REFRESH_IN_FLIGHT.with(|f| f.set(true));
            PENDING_REVIEW_FILTER.with(|slot| *slot.borrow_mut() = None);
            enqueue(Request::ListReviews { filter }, &ui, "loading reviews…");
        });
    }
    {
        let ui = main.as_weak();
        main.on_review_selected(move |index| {
            REVIEW_INDEX.with(|slot| *slot.borrow_mut() = index as isize);
            // Single preview request per selection: `apply_review_detail`
            // already sends `LoadPreview` for the selected case — a second
            // one here raced it and flashed stale previews.
            if let Some(w) = ui.upgrade() {
                apply_review_detail(&w);
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
            let image_id = REVIEW_CASES_CACHE.with(|slot| {
                slot.borrow()
                    .iter()
                    .find(|c| c.case_number == case_number as i64)
                    .and_then(|c| c.image_file_id.clone())
            });
            if let Some(image_id) = image_id {
                let ui2 = ui.clone();
                open_image_detail_by_id(&ui2, &image_id);
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
        main.on_bestlaps_detail_requested(move |image_file_id| {
            if image_file_id.is_empty() {
                return;
            }
            if let Some(w) = ui.upgrade() {
                w.set_page("image-detail".into());
                w.set_detail_loaded(false);
                set_status(&w, "loading image detail…");
            }
            enqueue(
                Request::LoadImageDetail {
                    image_id: image_file_id.to_string(),
                },
                &ui,
                "loading image detail…",
            );
        });
    }
    {
        let ui = main.as_weak();
        main.on_doctor_requested(move || {
            enqueue(Request::RunFullDoctor, &ui, "running doctor…");
        });
    }
    {
        let ui = main.as_weak();
        main.on_overview_requested(move || {
            enqueue(Request::RefreshOverview, &ui, "refreshing overview…");
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
            // NOTE: no `page == "image-debug"` branch — the standalone page
            // was folded into Diagnostics ("diagnostics" below); nothing
            // navigates to "image-debug" anymore.
            if page == "logs" {
                send_request(Request::LoadLogs);
            }
            if page == "best-laps" {
                send_request(Request::ListBestLaps);
            }
            if page == "diagnostics" {
                send_request(Request::RefreshOverview);
                // Preload Image Debug cases so the embedded Diagnostics → Image Debug tab
                // (which replaced the standalone image-debug page) is populated without a manual Refresh.
                send_request(Request::ListImageDebugCases {
                    filter: forza_app::ImageDebugFilter::default(),
                });
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
            let seq = SETTINGS_PREVIEW_SEQ.with(|s| {
                s.set(s.get().wrapping_add(1));
                s.get()
            });
            enqueue(
                Request::PreviewSettings { changes, seq },
                &ui,
                "validating…",
            );
        });
    }
    {
        let ui = main.as_weak();
        main.on_discard_settings(move || {
            PENDING_SETTINGS.with(|slot| slot.borrow_mut().clear());
            // Invalidate in-flight previews so one arriving late cannot
            // resurrect the discarded pending rows.
            SETTINGS_PREVIEW_SEQ.with(|s| s.set(s.get().wrapping_add(1)));
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
            SETTINGS_PREVIEW_SEQ.with(|s| s.set(s.get().wrapping_add(1)));
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
                w.set_page("diagnostics".into());
                w.set_diagnostics_tab("debug".into());
            }
            enqueue(
                Request::LoadImageDebugDetail {
                    image_file_id: image_file_id.to_string(),
                    selected_result_id: None,
                },
                &ui,
                "opening image debug…",
            );
            // Also ensure the debug cases list is loaded when navigating via detail link
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
    {
        let ui = main.as_weak();
        main.on_logs_clear_requested(move |which| {
            // Confirm via native dialog like Python QMessageBox
            let title = format!("Clear {} log?", which);
            let body = format!("Clear {} log file? This cannot be undone.", which);
            let confirm = rfd::MessageDialog::new()
                .set_title(title)
                .set_description(body)
                .set_buttons(rfd::MessageButtons::YesNo)
                .set_level(rfd::MessageLevel::Warning)
                .show();
            if confirm == rfd::MessageDialogResult::Yes {
                enqueue(
                    Request::ClearLogs {
                        which: which.to_string(),
                    },
                    &ui,
                    "clearing log…",
                );
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_logs_open_folder(move || {
            enqueue(Request::OpenLogFolder, &ui, "opening log folder…");
        });
    }
    {
        let ui = main.as_weak();
        main.on_logs_search_changed(move |query| {
            let q = query.to_string().to_lowercase();
            let (app_raw, err_raw) = (
                LOGS_APP_RAW.with(|s| s.borrow().clone()),
                LOGS_ERROR_RAW.with(|s| s.borrow().clone()),
            );
            if let Some(w) = ui.upgrade() {
                let filter = |text: &str| -> String {
                    if q.is_empty() {
                        text.to_string()
                    } else {
                        text.lines()
                            .filter(|l| l.to_lowercase().contains(&q))
                            .collect::<Vec<_>>()
                            .join("\n")
                    }
                };
                let app_f = filter(&app_raw);
                let err_f = filter(&err_raw);
                w.set_app_log_text(app_f.clone().into());
                w.set_error_log_text(err_f.clone().into());
                let shown = if w.get_logs_tab() == "app" {
                    &app_f
                } else {
                    &err_f
                };
                let cnt = if q.is_empty() {
                    "".to_string()
                } else {
                    format!("{} matching line(s)", shown.lines().count())
                };
                w.set_logs_status(cnt.into());
            }
        });
    }

    {
        let ui = main.as_weak();
        main.on_debug_filter_changed(move |status, backend, model, prompt, run| {
            let filter = forza_app::ImageDebugFilter {
                status: if status == "all" || status.is_empty() {
                    None
                } else {
                    Some(status.to_string())
                },
                backend: if backend == "all" || backend.is_empty() {
                    None
                } else {
                    Some(backend.to_string())
                },
                model: if model == "all" || model.is_empty() {
                    None
                } else {
                    Some(model.to_string())
                },
                prompt_name: if prompt == "all" || prompt.is_empty() {
                    None
                } else {
                    Some(prompt.to_string())
                },
                run_id: if run == "all" || run.is_empty() {
                    None
                } else {
                    Some(run.to_string())
                },
            };
            enqueue(
                Request::ListImageDebugCases { filter },
                &ui,
                "filtering debug cases…",
            );
        });
    }
    {
        let ui = main.as_weak();
        main.on_about_requested(move || {
            if let Some(w) = ui.upgrade() {
                let cfg_path = CONFIG_PATH.with(|p| p.borrow().clone());
                let about = format!(
                    "Forza Motorsport Results Extractor\nVersion: {}\nConfig: {}\nDatabase: {}\nGamertag: {}\nDoctor: {}\nOverview: {} · {} · {}",
                    forza_app::APP_VERSION,
                    cfg_path.display(),
                    w.get_context_db(),
                    w.get_context_gamertag(),
                    w.get_doctor_summary(),
                    w.get_overview_schema(),
                    w.get_overview_inventory(),
                    w.get_overview_review()
                );
                w.set_about_text(about.into());
                w.set_about_visible(true);
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_open_repository_requested(move || {
            // Same repository URL as the Python About dialog.
            if opener::open("https://github.com/Bujica/forza-motorsport-results-extractor").is_err()
                && let Some(w) = ui.upgrade()
            {
                w.set_status_text("could not open repository URL".into());
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_copy_diagnostics_requested(move || {
            if let Some(w) = ui.upgrade() {
                let text = w.get_about_text().to_string();
                // Windows clipboard via `clip` (no extra crate) — best effort
                let copied = (|| {
                    use std::io::Write;
                    let mut child = std::process::Command::new("cmd")
                        .args(["/C", "clip"])
                        .stdin(std::process::Stdio::piped())
                        .spawn()
                        .map_err(|e| e.to_string())?;
                    if let Some(stdin) = child.stdin.as_mut() {
                        stdin
                            .write_all(text.as_bytes())
                            .map_err(|e| e.to_string())?;
                    }
                    let _ = child.wait();
                    Ok::<(), String>(())
                })();
                match copied {
                    Ok(()) => w.set_status_text("diagnostics copied to clipboard".into()),
                    Err(e) => w.set_status_text(format!("copy failed: {e}").into()),
                }
            }
        });
    }

    // ── Live extraction runner (own thread, cooperative cancel) ──────────
    {
        let ui = main.as_weak();
        main.on_start_run(move |dry_run, force, retry, debug| {
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
                // Defensive: never let a stale selection survive a refused
                // start; the next Run All must mean "all".
                RUN_SELECTED_IDS.with(|slot| *slot.borrow_mut() = None);
                if let Some(w) = ui.upgrade() {
                    set_status(&w, "a run is already active");
                }
                return;
            }
            let Some(params) = RUN_CONFIG.with(|slot| slot.borrow().clone()) else {
                RUN_SELECTED_IDS.with(|slot| *slot.borrow_mut() = None);
                return;
            };
            let params = forza_app::RunParams {
                force,
                retry_errors: retry && !force,
                selected_image_file_ids: RUN_SELECTED_IDS.with(|slot| slot.borrow_mut().take()),
                verbose: debug,
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
                            if !cancelled {
                                w.set_run_percent(100.0);
                            }
                        }
                        // Refresh derived views after a run, keeping the
                        // user's active filters (forced defaults used to show
                        // a table that no longer matched the filter bar).
                        // Overview included: its DB snapshot is stale after a
                        // run (Python marks diagnostics pending here).
                        send_request(Request::RefreshOverview);
                        send_request(Request::RefreshInventory {
                            filter: current_inventory_filter(),
                        });
                        send_request(Request::ListBestLaps);
                        send_request(Request::ListReviews {
                            filter: REVIEW_FILTER.with(|s| s.borrow().clone()),
                        });
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
