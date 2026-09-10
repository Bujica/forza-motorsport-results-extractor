//! Doctor/Overview/Rebuild wiring.

use slint::ComponentHandle;

use crate::MainWindow;
use crate::ui_state::enqueue;
use crate::worker::Request;

/// Wire the Doctor/Overview/Rebuild callbacks.
pub(crate) fn wire_maintenance(main: &MainWindow) {
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
}
