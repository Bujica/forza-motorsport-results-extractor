//! Settings wiring.

use slint::ComponentHandle;

use crate::MainWindow;
use crate::ui_state::{PENDING_SETTINGS, SETTINGS_PREVIEW_SEQ, enqueue};
use crate::worker::Request;

/// Wire the Settings callbacks.
pub(crate) fn wire_settings(main: &MainWindow) {
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
}
