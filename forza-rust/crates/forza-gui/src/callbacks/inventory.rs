//! Images-page wiring.

use slint::ComponentHandle;

use crate::MainWindow;
use crate::ui_state::{
    INVENTORY_REFRESH_IN_FLIGHT, LIST_MODEL, PENDING_INVENTORY_FILTER, ROW_CACHE, RUN_CONTROL,
    RUN_SELECTED_IDS, SELECTED_IMAGE_IDS, SELECTION_ANCHOR, SORT_STATE, current_inventory_filter,
    enqueue, image_items, remember_inventory_filter, send_request, set_status,
    update_image_selection,
};
use crate::worker::Request;
use forza_app::{ImageInventoryEntry, ImageInventoryFilter};

/// Re-sort the cached rows per SORT_STATE and refresh the visible model and
/// the header arrows.
pub(super) fn apply_inventory_sort(ui: &MainWindow) {
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
            4 => {
                // Group-aware like Python `_group_sort_key`: members inherit
                // the canonical name so each duplicate stays next to its
                // canonical; canonical first, then children by own name.
                // Packed into one string (`\0` sorts before any name char).
                let group = e
                    .canonical_name
                    .clone()
                    .unwrap_or_else(|| e.name.clone())
                    .to_lowercase();
                let role = u8::from(e.duplicate_label == "Duplicate");
                (
                    format!("{group}\0{role}\0{}", e.name.to_lowercase()),
                    String::new(),
                )
            }
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
pub(super) fn update_selection_summary(ui: &MainWindow) {
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

/// Wire the Images-page callbacks.
pub(crate) fn wire_inventory(main: &MainWindow) {
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
            let Ok(index) = usize::try_from(index) else {
                return;
            };
            SELECTION_ANCHOR.with(|slot| *slot.borrow_mut() = index);
            let id = ROW_CACHE.with(|rows| rows.borrow().get(index).map(|e| e.id.clone()));
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
            let Ok(index) = usize::try_from(index) else {
                return;
            };
            SELECTION_ANCHOR.with(|slot| *slot.borrow_mut() = index);
            let id = ROW_CACHE.with(|rows| rows.borrow().get(index).map(|e| e.id.clone()));
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
            // A negative index (`-1` = no selection) must never reach the
            // anchor arithmetic below: `usize::MAX + 1` would overflow.
            let Ok(end) = usize::try_from(end) else {
                return;
            };
            let (ids, anchor) = ROW_CACHE.with(|rows| {
                let rows = rows.borrow();
                let anchor = SELECTION_ANCHOR.with(|slot| *slot.borrow());
                // Both directions include the target row: down is
                // [anchor, end], up is [end, anchor]. (The old up-branch
                // started at end+1 and silently dropped the clicked row.)
                let (lo, hi) = if anchor <= end {
                    (anchor, end + 1)
                } else {
                    (end, anchor + 1)
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
            let Ok(column) = usize::try_from(column) else {
                return;
            };
            SORT_STATE.with(|slot| {
                let mut state = slot.borrow_mut();
                let (current_col, current_asc) = *state;
                let ascending = if current_col == column {
                    !current_asc
                } else {
                    true
                };
                *state = (column, ascending);
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
            // Preview first (Python `confirm_rename_plan` parity): the panel
            // shows totals plus one `source -> target` line per change, and
            // `on_confirm_rename` below executes only on Confirm.
            enqueue(
                Request::PreviewRename {
                    image_ids: selected,
                },
                &ui,
                "planning rename…",
            );
        });
    }
    {
        let ui = main.as_weak();
        main.on_execute_rename(move || {
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
}
