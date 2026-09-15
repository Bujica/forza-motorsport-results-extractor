//! About/repository wiring.

use slint::ComponentHandle;

use crate::MainWindow;
use crate::ui_state::CONFIG_PATH;

/// Wire the About/repository callbacks.
pub(crate) fn wire_about(main: &MainWindow) {
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
}
