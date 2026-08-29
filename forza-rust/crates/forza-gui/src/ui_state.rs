//! UI-thread state: widget-adjacent models, caches and small helpers.
//! Everything here lives in UI-thread locals and is never shared across
//! threads (migration plan §4.9 threading contract).

use std::cell::RefCell;
use std::collections::BTreeMap;
use std::path::PathBuf;
use std::rc::Rc;
use std::sync::mpsc;

use slint::{Model, VecModel};

use crate::{
    BestLapItem, DebugCaseItem, DebugResultComboItem, DetailAttemptItem, DetailLapItem,
    DetailResultItem, DetailReviewItem, ImageItem, MainWindow, ReviewItem, SettingItem,
    worker::Request,
};
use forza_app::ImageInventoryEntry;

thread_local! {
    pub(crate) static LIST_MODEL: RefCell<Option<Rc<VecModel<ImageItem>>>> = const { RefCell::new(None) };
    pub(crate) static ROW_CACHE: RefCell<Vec<ImageInventoryEntry>> = const { RefCell::new(Vec::new()) };
    pub(crate) static SELECTED_IMAGE_IDS: RefCell<Vec<String>> = const { RefCell::new(Vec::new()) };
    pub(crate) static RUN_SELECTED_IDS: RefCell<Option<Vec<String>>> = const { RefCell::new(None) };
    pub(crate) static RUN_START: RefCell<Option<std::time::Instant>> = const { RefCell::new(None) };
    pub(crate) static REVIEW_MODEL: RefCell<Option<Rc<VecModel<ReviewItem>>>> = const { RefCell::new(None) };
    pub(crate) static BESTLAP_MODEL: RefCell<Option<Rc<VecModel<BestLapItem>>>> = const { RefCell::new(None) };
    pub(crate) static GAMERTAG: RefCell<String> = const { RefCell::new(String::new()) };
    pub(crate) static RUN_LOG: RefCell<Option<Rc<VecModel<slint::SharedString>>>> = const { RefCell::new(None) };
    pub(crate) static RUN_CONTROL: RefCell<Option<forza_app::RunControl>> = const { RefCell::new(None) };
    pub(crate) static RUN_CONFIG: RefCell<Option<forza_app::RunParams>> = const { RefCell::new(None) };
    pub(crate) static DETAIL_CACHE: RefCell<Option<forza_app::ImageDetailData>> = const { RefCell::new(None) };
    pub(crate) static DETAIL_INDEX: RefCell<i32> = const { RefCell::new(-1) };
    pub(crate) static DETAIL_LAP_MODEL: RefCell<Option<Rc<VecModel<DetailLapItem>>>> = const { RefCell::new(None) };
    pub(crate) static DETAIL_REVIEW_MODEL: RefCell<Option<Rc<VecModel<DetailReviewItem>>>> = const { RefCell::new(None) };
    pub(crate) static DETAIL_RESULT_MODEL: RefCell<Option<Rc<VecModel<DetailResultItem>>>> = const { RefCell::new(None) };
    pub(crate) static DETAIL_ATTEMPT_MODEL: RefCell<Option<Rc<VecModel<DetailAttemptItem>>>> = const { RefCell::new(None) };
    pub(crate) static SETTINGS_MODEL: RefCell<Option<Rc<VecModel<SettingItem>>>> = const { RefCell::new(None) };
    pub(crate) static PENDING_SETTINGS: RefCell<BTreeMap<String, String>> =
        const { RefCell::new(BTreeMap::new()) };
    pub(crate) static SETTINGS_LOADED: RefCell<bool> = const { RefCell::new(false) };
    pub(crate) static DEBUG_CASE_MODEL: RefCell<Option<Rc<VecModel<DebugCaseItem>>>> = const { RefCell::new(None) };
    pub(crate) static DEBUG_RESULT_MODEL: RefCell<Option<Rc<VecModel<DebugResultComboItem>>>> = const { RefCell::new(None) };
    pub(crate) static DEBUG_DETAIL_CACHE: RefCell<Option<forza_db::image_debug::ImageDebugDetail>> = const { RefCell::new(None) };
    pub(crate) static DEBUG_CASES_CACHE: RefCell<Vec<forza_db::image_debug::ImageDebugCase>> = const { RefCell::new(Vec::new()) };
    pub(crate) static CONFIG_PATH: RefCell<PathBuf> = const { RefCell::new(PathBuf::new()) };
}

/// Rate/ETA readout for the run progress bar, measured from the run's
/// Started event (includes model preflight, so the first estimates are
/// pessimistic and converge as images complete).
pub(crate) fn compute_rate_eta(
    done: i32,
    total: i32,
    start: Option<std::time::Instant>,
) -> (String, String) {
    let Some(start) = start else {
        return (String::new(), String::new());
    };
    let elapsed = start.elapsed().as_secs_f64();
    if done <= 0 || elapsed < 0.5 {
        return (String::from("—"), String::from("—"));
    }
    let per_image = elapsed / done as f64;
    let rate = format!("{:.1} img/min", 60.0 / per_image);
    let remaining = (total - done).max(0) as f64 * per_image;
    let eta = if remaining >= 3600.0 {
        format!(
            "{:.0}h{:02.0}m",
            remaining / 3600.0,
            (remaining % 3600.0) / 60.0
        )
    } else if remaining >= 60.0 {
        format!("{:.0}m {:02.0}s", remaining / 60.0, remaining % 60.0)
    } else {
        format!("{:.0}s", remaining)
    };
    (rate, eta)
}

pub(crate) fn append_run_log(line: String) {
    RUN_LOG.with(|slot| {
        if let Some(model) = slot.borrow().as_ref() {
            model.push(line.into());
            while model.row_count() > 500 {
                model.remove(0);
            }
        }
    });
}

pub(crate) fn set_status(ui: &MainWindow, text: &str) {
    ui.set_status_text(text.into());
}

pub(crate) fn run_info_line(cfg: &forza_config::AppConfig) -> String {
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

pub(crate) fn image_items(entries: &[ImageInventoryEntry]) -> Vec<ImageItem> {
    SELECTED_IMAGE_IDS.with(|selected| {
        let selected = selected.borrow();
        entries
            .iter()
            .map(|e| ImageItem {
                id: e.id.clone().into(),
                name: e.name.clone().into(),
                race_date: e.race_date.clone().unwrap_or_default().into(),
                semantic: e.semantic_name.clone().unwrap_or_default().into(),
                processing: e.processing_status.clone().into(),
                best_lap: e.best_lap_status.clone().into(),
                file_status: e.file_status.clone().into(),
                duplicate: e.duplicate_label.clone().into(),
                selected: selected.iter().any(|id| id == &e.id),
            })
            .collect()
    })
}

pub(crate) fn update_image_selection(ui: &MainWindow) {
    let count = SELECTED_IMAGE_IDS.with(|ids| ids.borrow().len() as i32);
    ui.set_selected_image_count(count);
    LIST_MODEL.with(|slot| {
        if let Some(model) = slot.borrow().as_ref() {
            let rows = ROW_CACHE.with(|cache| cache.borrow().clone());
            model.set_vec(image_items(&rows));
        }
    });
}

thread_local! {
    pub(crate) static WORKER_TX: std::cell::OnceCell<mpsc::Sender<Request>> =
        const { std::cell::OnceCell::new() };
}

pub(crate) fn send_request(request: Request) {
    WORKER_TX.with(|slot| {
        if let Some(tx) = slot.get() {
            let _ = tx.send(request);
        }
    });
}

pub(crate) fn enqueue(request: Request, ui: &slint::Weak<MainWindow>, loading: &str) {
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
