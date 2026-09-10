//! Logs wiring.

use slint::ComponentHandle;

use crate::MainWindow;
use crate::ui_state::{LOGS_APP_RAW, LOGS_ERROR_RAW, enqueue};
use crate::worker::Request;

/// Wire the Logs callbacks.
pub(crate) fn wire_logs(main: &MainWindow) {
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
}
