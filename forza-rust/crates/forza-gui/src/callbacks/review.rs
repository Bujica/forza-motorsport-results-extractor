//! Review-queue wiring.

use std::rc::Rc;

use slint::{ComponentHandle, ModelRc, VecModel};

use super::detail::open_image_detail_by_id;
use crate::MainWindow;
use crate::ui_state::{
    PENDING_REVIEW_FILTER, REVIEW_CASES_CACHE, REVIEW_FILTER, REVIEW_INDEX,
    REVIEW_REFRESH_IN_FLIGHT, enqueue, send_request,
};
use crate::worker::Request;
use forza_app::ReviewQueueFilter;

pub(crate) fn set_review_track_model(main: &MainWindow, values: Vec<slint::SharedString>) {
    main.set_review_tracks(ModelRc::from(Rc::new(VecModel::from(values))));
}

pub(crate) fn set_review_class_model(main: &MainWindow, values: Vec<slint::SharedString>) {
    main.set_review_classes(ModelRc::from(Rc::new(VecModel::from(values))));
}

/// Outcome label for display. The stored `outcome` vocabulary
/// (`pending|confirmed|model_error`) has no system-resolved value by design
/// design (Python parity, CHECK-enforced), so auto-resolved rows keep
/// `outcome='pending'` in the DB. The table/detail would then read as
/// "awaiting action" for a closed case — show the lifecycle truth instead.
pub(super) fn display_outcome(status: &str, outcome: Option<&str>) -> String {
    if status == "auto_resolved" {
        return "auto_resolved".to_string();
    }
    outcome.unwrap_or_default().to_string()
}

/// Build the details-panel text for the selected review case (Python
/// details grid labels) and refresh the reason/suggestion hints.
pub(super) fn apply_review_detail(ui: &MainWindow) {
    let case = REVIEW_INDEX.with(|slot| *slot.borrow());
    let entry = REVIEW_CASES_CACHE.with(|slot| {
        let cache = slot.borrow();
        if case >= 0 && (case as usize) < cache.len() {
            Some(cache[case as usize].clone())
        } else {
            None
        }
    });

    match entry {
        Some(c) => {
            ui.set_review_detail_title(format!("Case #{}", c.case_number).into());
            let temp = c
                .temp_f
                .map(|t| format!("{t:.1} °F"))
                .unwrap_or_else(|| "-".to_string());
            let decision = match (&c.decision_field, &c.corrected_value) {
                (Some(d), Some(cv)) if !d.is_empty() => {
                    let before = c.model_value.as_deref().unwrap_or("?");
                    format!("{d}: {before} -> {cv}")
                }
                _ => "—".to_string(),
            };
            let current_driver = c.driver.clone().unwrap_or_default();
            let current_car = c.car.clone().unwrap_or_default();
            let current_lap = c
                .current_best_lap
                .clone()
                .or_else(|| c.best_lap.clone())
                .unwrap_or_default();
            ui.set_review_detail_lines(
                format!(
                    "Case: {}\nStable ID: {}\nOutcome: {}\nReason: {}\nTrigger: {}\nModel value: {}\nCorrected value: {}\nDecision: {}\nError: {}\nResolution: {}\nFile: {}\nCurrent track: {}\nCurrent class: {}\nCurrent weather: {}\nTemp: {}\nCurrent driver: {}\nCurrent car: {}\nCurrent lap: {}",
                    c.case_number,
                    c.image_file_id.clone().unwrap_or_default(),
                    display_outcome(&c.status, c.outcome.as_deref()),
                    c.reason,
                    c.trigger.clone().unwrap_or_default(),
                    c.model_value.clone().unwrap_or_default(),
                    c.corrected_value.clone().unwrap_or_default(),
                    decision,
                    c.error_type.clone().unwrap_or_default(),
                    c.resolution_note.clone().unwrap_or_default(),
                    c.source_file.clone().unwrap_or_default(),
                    c.track.clone().unwrap_or_default(),
                    c.race_class.clone().unwrap_or_default(),
                    c.weather.clone().unwrap_or_default(),
                    temp,
                    current_driver,
                    current_car,
                    current_lap,
                )
                .into(),
            );
            ui.set_review_reason_note(c.reason.clone().into());
            ui.set_review_suggestions(String::new().into());
            // Pre-fill correction inputs with the model's value (Python
            // parity: the field shows e.g. "Cadillac #3 ATS" so a correct
            // read is one Apply click). Prefer an existing corrected value
            // when revisiting a decided case; clear otherwise so text never
            // leaks from the previously selected case.
            let prefill = c
                .corrected_value
                .clone()
                .filter(|v| !v.is_empty())
                .or_else(|| c.model_value.clone())
                .unwrap_or_default();
            if c.reason == "car" {
                ui.set_review_car_text(prefill.into());
                ui.set_review_driver_text(String::new().into());
            } else if c.reason == "driver_name" {
                ui.set_review_driver_text(prefill.into());
                ui.set_review_car_text(String::new().into());
            } else {
                ui.set_review_car_text(String::new().into());
                ui.set_review_driver_text(String::new().into());
            }
            if let Some(image_file_id) = c.image_file_id.clone() {
                send_request(Request::LoadPreview { image_file_id });
            } else {
                ui.set_review_has_preview(false);
            }
        }
        None => {
            ui.set_review_detail_title("Review queue is clear.".into());
            ui.set_review_detail_lines(String::new().into());
            ui.set_review_reason_note(String::new().into());
            ui.set_review_suggestions(String::new().into());
            ui.set_review_has_preview(false);
        }
    }
}

/// Wire the Review-queue callbacks.
pub(crate) fn wire_review(main: &MainWindow) {
    {
        let ui = main.as_weak();
        main.on_reviews_requested(move || {
            let filter = REVIEW_FILTER.with(|slot| slot.borrow().clone());
            PENDING_REVIEW_FILTER.with(|slot| *slot.borrow_mut() = Some(filter.clone()));
            if REVIEW_REFRESH_IN_FLIGHT.with(|f| f.get()) {
                return;
            }
            REVIEW_REFRESH_IN_FLIGHT.with(|f| f.set(true));
            PENDING_REVIEW_FILTER.with(|slot| *slot.borrow_mut() = None);
            enqueue(Request::ListReviews { filter }, &ui, "loading reviews…");
        });
    }
    {
        let ui = main.as_weak();
        main.on_review_filter_changed(move |status, reason, outcome, run| {
            REVIEW_FILTER.with(|slot| {
                *slot.borrow_mut() = ReviewQueueFilter {
                    bucket: status.to_string(),
                    reason: Some(reason.to_string()),
                    outcome: Some(outcome.to_string()),
                    run_id: Some(run.to_string()),
                    image_file_id: None,
                };
            });
            let filter = REVIEW_FILTER.with(|slot| slot.borrow().clone());
            PENDING_REVIEW_FILTER.with(|slot| *slot.borrow_mut() = Some(filter.clone()));
            if REVIEW_REFRESH_IN_FLIGHT.with(|f| f.get()) {
                return;
            }
            REVIEW_REFRESH_IN_FLIGHT.with(|f| f.set(true));
            PENDING_REVIEW_FILTER.with(|slot| *slot.borrow_mut() = None);
            enqueue(Request::ListReviews { filter }, &ui, "loading reviews…");
        });
    }
    {
        let ui = main.as_weak();
        main.on_review_selected(move |index| {
            REVIEW_INDEX.with(|slot| *slot.borrow_mut() = index as isize);
            // Single preview request per selection: `apply_review_detail`
            // already sends `LoadPreview` for the selected case — a second
            // one here raced it and flashed stale previews.
            if let Some(w) = ui.upgrade() {
                apply_review_detail(&w);
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_review_apply(move |case_number, field, value| {
            enqueue(
                Request::DecideCase {
                    case_number: case_number as i64,
                    field: field.into(),
                    value: value.into(),
                },
                &ui,
                "applying correction…",
            );
        });
    }
    {
        let ui = main.as_weak();
        main.on_review_reopen(move |case_number| {
            enqueue(
                Request::ReopenCase {
                    case_number: case_number as i64,
                },
                &ui,
                "reopening case…",
            );
        });
    }
    {
        let ui = main.as_weak();
        main.on_review_open_detail(move |case_number| {
            let image_id = REVIEW_CASES_CACHE.with(|slot| {
                slot.borrow()
                    .iter()
                    .find(|c| c.case_number == case_number as i64)
                    .and_then(|c| c.image_file_id.clone())
            });
            if let Some(image_id) = image_id {
                let ui2 = ui.clone();
                open_image_detail_by_id(&ui2, &image_id);
            }
        });
    }
    {
        main.on_review_preview_requested(move |image_file_id| {
            send_request(Request::LoadPreview {
                image_file_id: image_file_id.to_string(),
            });
        });
    }
}

#[cfg(test)]
mod tests {
    use super::display_outcome;

    #[test]
    fn auto_resolved_rows_show_lifecycle_not_stale_pending() {
        assert_eq!(
            display_outcome("auto_resolved", Some("pending")),
            "auto_resolved"
        );
        assert_eq!(display_outcome("auto_resolved", None), "auto_resolved");
        assert_eq!(display_outcome("open", Some("pending")), "pending");
        assert_eq!(display_outcome("resolved", Some("confirmed")), "confirmed");
        assert_eq!(display_outcome("open", None), "");
    }
}
