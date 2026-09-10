//! Image-debug wiring.

use slint::ComponentHandle;

use crate::MainWindow;
use crate::ui_state::{DEBUG_CASES_CACHE, DEBUG_DETAIL_CACHE, enqueue};
use crate::worker::Request;

/// Wire the image-debug and debug-filter callbacks.
pub(crate) fn wire_debug(main: &MainWindow) {
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
}
