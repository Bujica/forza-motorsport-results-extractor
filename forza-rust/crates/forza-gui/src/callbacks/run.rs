//! Live-extraction runner wiring.

use slint::ComponentHandle;

use crate::MainWindow;
use crate::ui_state::{
    REVIEW_FILTER, RUN_CONFIG, RUN_CONTROL, RUN_SELECTED_IDS, RUN_START, append_run_log,
    compute_rate_eta, current_inventory_filter, enqueue, send_request, set_status,
};
use crate::worker::Request;

/// Wire the live-extraction runner callbacks.
pub(crate) fn wire_run(main: &MainWindow) {
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
            let start_line = format!(
                "[start] {} model={} force={} retry_errors={} workers={}",
                forza_app::APP_VERSION,
                params.model,
                params.force,
                params.retry_errors,
                params.workers,
            );
            append_run_log(start_line.clone());
            forza_app::append_log_file(&params.log_file, &start_line);

            // File logging (Python `logging_setup` parity): without this the
            // configured log file stays empty and the Logs page shows
            // "Log file not found" forever. The errors sibling gets failures.
            let log_file = params.log_file.clone();
            let errors_file = forza_app::errors_log_path(&params.log_file);
            let ui = ui.clone();
            let _handle = forza_app::spawn_extraction(params, control, move |event| {
                let ui = ui.clone();
                // Cloned per event: the inner callback must stay `'static`.
                let log_file = log_file.clone();
                let errors_file = errors_file.clone();
                let _ = slint::invoke_from_event_loop(move || match event {
                    forza_app::RunEvent::Started { run_id, total } => {
                        let line =
                            format!("[run {run_id}] {total} file(s) considered");
                        append_run_log(line.clone());
                        forza_app::append_log_file(&log_file, &line);
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
                        let line = format!(
                            "plan: new={new} cached={cached} batch={batch} existing={existing} skipped={skipped}"
                        );
                        append_run_log(line.clone());
                        forza_app::append_log_file(&log_file, &line);
                    }
                    forza_app::RunEvent::ImageStarted { name } => {
                        let line = format!("→ {name}");
                        append_run_log(line.clone());
                        forza_app::append_log_file(&log_file, &line);
                    }
                    forza_app::RunEvent::ImageDone { name, ok, laps } => {
                        let line = format!(
                            "  {} {name} ({laps} lap(s))",
                            if ok { "✓" } else { "✗" }
                        );
                        append_run_log(line.clone());
                        forza_app::append_log_file(&log_file, &line);
                        if !ok {
                            forza_app::append_log_file(&errors_file, &line);
                        }
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
                    forza_app::RunEvent::Log(line) => {
                        append_run_log(line.clone());
                        forza_app::append_log_file(&log_file, &line);
                    }
                    forza_app::RunEvent::Finished { cancelled, processed, succeeded, failed, elapsed_s } => {
                        let line = format!(
                            "[done] cancelled={cancelled} processed={processed} ok={succeeded} fail={failed} in {elapsed_s:.1}s"
                        );
                        append_run_log(line.clone());
                        forza_app::append_log_file(&log_file, &line);
                        if failed > 0 {
                            forza_app::append_log_file(&errors_file, &line);
                        }
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
                        let line = format!("[failed] {message}");
                        append_run_log(line.clone());
                        forza_app::append_log_file(&log_file, &line);
                        forza_app::append_log_file(&errors_file, &line);
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
}
