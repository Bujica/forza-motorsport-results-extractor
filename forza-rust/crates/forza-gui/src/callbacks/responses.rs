//! Worker-response dispatcher.

use std::path::Path;
use std::rc::Rc;

use slint::{ModelRc, VecModel};

use super::bestlaps::apply_bestlaps_filters;
use super::inventory::{apply_inventory_sort, update_selection_summary};
use super::review::{apply_review_detail, display_outcome};
use crate::detail_views::{
    apply_debug_cases, apply_debug_detail, apply_image_detail, apply_settings,
};
use crate::ui_state::{
    BESTLAP_ALL, BESTLAP_FILTER, INVENTORY_REFRESH_IN_FLIGHT, LIST_MODEL, LOGS_APP_RAW,
    LOGS_ERROR_RAW, PENDING_IMPORT_MESSAGE, PENDING_INVENTORY_FILTER, PENDING_REVIEW_FILTER,
    REVIEW_CASES_CACHE, REVIEW_FILTER, REVIEW_INDEX, REVIEW_MODEL, REVIEW_REFRESH_IN_FLIGHT,
    ROW_CACHE, SELECTED_IMAGE_IDS, SETTINGS_PREVIEW_SEQ, append_run_log, current_inventory_filter,
    enqueue, image_items, send_request, set_status, update_image_selection,
};
use crate::worker::{Request, Response};
use crate::{DoctorCheckItem, MainWindow, ReviewItem};
use forza_app::ReviewQueueFilter;

/// Dispatch worker responses onto widgets.
///
/// Extracted from `run()`: this match lived inline in the
/// `invoke_from_event_loop` closure; a named function keeps the dispatcher
/// grep-able and `run()` readable.
pub(crate) fn handle_response(response: Response, ui: slint::Weak<MainWindow>) {
    match response {
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
            }
            INVENTORY_REFRESH_IN_FLIGHT.with(|f| f.set(false));
            if let Some(pending) = PENDING_INVENTORY_FILTER.with(|slot| slot.borrow_mut().take()) {
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
                                    outcome: display_outcome(&c.status, c.outcome.as_deref())
                                        .into(),
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
                                    // Live lap resolved per case (Python
                                    // `_current_lap_label` parity):
                                    // current time first, stored
                                    // snapshot as fallback; "dirty"
                                    // only when the lap really is.
                                    lap: {
                                        let best = c
                                            .current_best_lap
                                            .clone()
                                            .or_else(|| c.best_lap.clone())
                                            .unwrap_or_default();
                                        let dirty = c.current_lap_dirty.unwrap_or(false);
                                        if best.is_empty() {
                                            String::new()
                                        } else if dirty {
                                            format!("{best} dirty")
                                        } else {
                                            best
                                        }
                                    }
                                    .into(),
                                    lap_dirty: c.current_lap_dirty.unwrap_or(false),
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
                            format!("{} review case(s) [{}]", entries.len(), filter.bucket).into(),
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
            if let Some(pending) = PENDING_REVIEW_FILTER.with(|slot| slot.borrow_mut().take()) {
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
                        let pending = PENDING_IMPORT_MESSAGE.with(|s| s.borrow_mut().take());
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
                        w.set_overview_configured_request(s.lm_configured_request.clone().into());
                        w.set_overview_configured_image(s.lm_configured_image.clone().into());
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
                            format!("db: {} · schema {}", s.schema_state, s.db_errors).into(),
                        );
                        w.set_status_text("overview refreshed".into());
                    }
                    Err(message) => w.set_status_text(format!("overview error: {message}").into()),
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
                    Err(message) => w.set_status_text(format!("clear failed: {message}").into()),
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
                        &format!("rescan: {available} back available, {missing} now missing"),
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
        Response::RenamePreview(result) => {
            if let Some(w) = ui.upgrade() {
                match result {
                    Ok(preview) => {
                        // Populate the inline confirmation panel (Python
                        // `confirm_rename_plan` parity): totals plus
                        // one `source -> target` line per change,
                        // capped so a 700-file batch cannot push the
                        // Confirm/Cancel buttons out of the panel.
                        const MAX_PREVIEW_LINES: usize = 100;
                        let lines: Vec<String> = preview
                            .plans
                            .iter()
                            .filter(|p| p.would_change)
                            .map(|p| {
                                let from = p
                                    .source
                                    .file_name()
                                    .map(|n| n.to_string_lossy().to_string())
                                    .unwrap_or_default();
                                let to = p
                                    .target
                                    .file_name()
                                    .map(|n| n.to_string_lossy().to_string())
                                    .unwrap_or_default();
                                format!("{from} -> {to}")
                            })
                            .collect();
                        w.set_rename_summary(
                            format!(
                                "Selected {} · Would rename {} · Missing {}",
                                preview.total, preview.would_change, preview.missing
                            )
                            .into(),
                        );
                        w.set_rename_plan_lines(if lines.is_empty() {
                            "No filename changes are required.".into()
                        } else if lines.len() > MAX_PREVIEW_LINES {
                            format!(
                                "{}\n… and {} more",
                                lines[..MAX_PREVIEW_LINES].join("\n"),
                                lines.len() - MAX_PREVIEW_LINES
                            )
                            .into()
                        } else {
                            lines.join("\n").into()
                        });
                        w.set_confirm_rename(true);
                    }
                    Err(message) => {
                        w.set_confirm_rename(false);
                        set_status(&w, format!("rename preview failed: {message}").as_str())
                    }
                }
            }
        }
        Response::RenameDone(result) => {
            if let Some(w) = ui.upgrade() {
                w.set_confirm_rename(false);
                match result {
                    Ok(message) => {
                        set_status(&w, &message);
                        INVENTORY_REFRESH_IN_FLIGHT.with(|f| f.set(true));
                        send_request(Request::RefreshInventory {
                            filter: current_inventory_filter(),
                        });
                    }
                    Err(message) => set_status(&w, format!("rename error: {message}").as_str()),
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
    }
}
