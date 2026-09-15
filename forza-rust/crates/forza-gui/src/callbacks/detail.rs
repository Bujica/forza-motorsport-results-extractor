//! Image-detail wiring.

use slint::ComponentHandle;

use crate::MainWindow;
use crate::detail_views::step_detail;
use crate::ui_state::{DETAIL_INDEX, ROW_CACHE, SETTINGS_LOADED, send_request, set_status};
use crate::worker::Request;

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
pub(super) fn open_image_detail_by_id(ui: &slint::Weak<MainWindow>, image_id: &str) {
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

/// Wire the image-detail and page-nav callbacks.
pub(crate) fn wire_detail(main: &MainWindow) {
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
}
