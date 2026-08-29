//! Apply functions: push worker/application data into the detail, settings
//! and image-debug views.

use slint::{Image, ModelRc, VecModel};
use std::path::Path;

use crate::ui_state::{
    DEBUG_CASE_MODEL, DEBUG_CASES_CACHE, DEBUG_DETAIL_CACHE, DEBUG_RESULT_MODEL,
    DETAIL_ATTEMPT_MODEL, DETAIL_CACHE, DETAIL_INDEX, DETAIL_LAP_MODEL, DETAIL_RESULT_MODEL,
    DETAIL_REVIEW_MODEL, GAMERTAG, PENDING_SETTINGS, ROW_CACHE, RUN_CONFIG, SETTINGS_MODEL,
    run_info_line, send_request, set_status,
};
use crate::worker::Request;
use crate::{
    DebugCaseItem, DebugResultComboItem, DetailAttemptItem, DetailLapItem, DetailResultItem,
    DetailReviewItem, MainWindow, SettingItem,
};
use forza_app::ImageInventoryFilter;

pub(crate) fn step_detail(ui: &slint::Weak<MainWindow>, delta: i32) {
    let index = DETAIL_INDEX.with(|slot| *slot.borrow()) + delta;
    let count = ROW_CACHE.with(|rows| rows.borrow().len()) as i32;
    if index < 0 || index >= count {
        return;
    }
    if let Some(w) = ui.upgrade() {
        w.set_selected_index(index);
    }
    if let Some(cb) = ui.upgrade() {
        cb.invoke_open_image_detail(index);
    }
}

/// Fill the detail page models from the loaded bundle (UI thread only).
pub(crate) fn apply_image_detail(ui: &slint::Weak<MainWindow>, data: forza_app::ImageDetailData) {
    use forza_app::ImageDetailData as Data;
    let Data {
        meta,
        laps,
        reviews,
        results,
        attempts,
    } = data;

    DETAIL_LAP_MODEL.with(|slot| {
        if let Some(model) = slot.borrow().as_ref() {
            let items: Vec<DetailLapItem> = laps
                .iter()
                .map(|l| DetailLapItem {
                    index: l.lap_index as i32,
                    track: l.track.clone().into(),
                    class: l.race_class.clone().into(),
                    driver: l.driver.clone().into(),
                    car: l.car.clone().into(),
                    time: l.best_lap.clone().into(),
                    flags: if l.is_best_lap {
                        "best".into()
                    } else if l.dirty {
                        "dirty".into()
                    } else {
                        "—".into()
                    },
                    dirty: l.dirty,
                    best: l.is_best_lap,
                })
                .collect();
            model.set_vec(items);
        }
    });
    DETAIL_REVIEW_MODEL.with(|slot| {
        if let Some(model) = slot.borrow().as_ref() {
            let items: Vec<DetailReviewItem> = reviews
                .iter()
                .map(|c| DetailReviewItem {
                    number: c.case_number as i32,
                    reason: c.reason.clone().into(),
                    trigger: c.trigger.clone().unwrap_or_default().into(),
                    driver: c.driver.clone().unwrap_or_default().into(),
                    track: c.track.clone().unwrap_or_default().into(),
                    model_value: c.model_value.clone().unwrap_or_default().into(),
                    status: c.status.clone().into(),
                })
                .collect();
            model.set_vec(items);
        }
    });
    DETAIL_RESULT_MODEL.with(|slot| {
        if let Some(model) = slot.borrow().as_ref() {
            let items: Vec<DetailResultItem> = results
                .iter()
                .map(|r| DetailResultItem {
                    run: r.run_id.clone().into(),
                    status: r.status.clone().into(),
                    model: r.model.clone().unwrap_or_default().into(),
                    attempts: r.attempt_count as i32,
                    duration: r
                        .duration_ms
                        .map(|ms| format!("{ms} ms"))
                        .unwrap_or_else(|| "—".into())
                        .into(),
                    tokens: r
                        .total_tokens
                        .map(|t| format!("{t} tok"))
                        .unwrap_or_else(|| "—".into())
                        .into(),
                    created: r.created_at.clone().into(),
                })
                .collect();
            model.set_vec(items);
        }
    });
    DETAIL_ATTEMPT_MODEL.with(|slot| {
        if let Some(model) = slot.borrow().as_ref() {
            let items: Vec<DetailAttemptItem> = attempts
                .iter()
                .map(|a| DetailAttemptItem {
                    number: a.attempt_number as i32,
                    reason: a.attempt_reason.clone().into(),
                    status: a.status.clone().into(),
                    accepted: a.accepted,
                    rejected: a.rejected_reason.clone().unwrap_or_default().into(),
                    model: a.model.clone().unwrap_or_default().into(),
                    duration: a
                        .duration_ms
                        .map(|ms| format!("{ms} ms"))
                        .unwrap_or_else(|| "—".into())
                        .into(),
                    tps: a
                        .tokens_per_second
                        .map(|t| format!("{t:.1} tok/s"))
                        .unwrap_or_else(|| "—".into())
                        .into(),
                    created: a.created_at.clone().into(),
                })
                .collect();
            model.set_vec(items);
        }
    });

    let meta_lines = format!(
        "id: {}\nhash: {}\nduplicate of: {}\ncurrent name: {}\nsemantic name: {}\nsize: {}\ndimensions: {} × {}\nbit depth: {}\ncolor mode: {}\nmime: {}\nformat: {}\nrace date: {} (source: {})\nfile status: {}\nbest lap status: {}\nprocessing: {}",
        meta.id,
        meta.file_hash,
        meta.duplicate_of_image_file_id
            .clone()
            .unwrap_or_else(|| "—".into()),
        meta.current_name.clone().unwrap_or_else(|| "—".into()),
        meta.semantic_name.clone().unwrap_or_else(|| "—".into()),
        meta.size_bytes
            .map(|b| format!("{b} bytes"))
            .unwrap_or_else(|| "—".into()),
        meta.width_px
            .map(|v| v.to_string())
            .unwrap_or_else(|| "?".into()),
        meta.height_px
            .map(|v| v.to_string())
            .unwrap_or_else(|| "?".into()),
        meta.bit_depth
            .map(|v| v.to_string())
            .unwrap_or_else(|| "—".into()),
        meta.color_mode.clone().unwrap_or_else(|| "—".into()),
        meta.mime_type.clone().unwrap_or_else(|| "—".into()),
        meta.image_format.clone().unwrap_or_else(|| "—".into()),
        meta.race_date.clone().unwrap_or_else(|| "—".into()),
        meta.race_datetime_source,
        meta.file_status,
        meta.best_lap_status,
        meta.processing_status,
    );

    // Preview: load the current file when it exists on disk.
    let preview = meta
        .current_path
        .as_ref()
        .filter(|p| Path::new(p).exists())
        .and_then(|p| Image::load_from_path(Path::new(p)).ok());
    let has_preview = preview.is_some();

    if let Some(w) = ui.upgrade() {
        w.set_detail_title(
            meta.current_name
                .clone()
                .unwrap_or_else(|| meta.id.clone())
                .into(),
        );
        w.set_detail_image_id(meta.id.clone().into());
        w.set_detail_meta(meta_lines.into());
        w.set_detail_badges(
            format!(
                "file: {} · best: {} · processing: {}",
                meta.file_status, meta.best_lap_status, meta.processing_status
            )
            .into(),
        );
        w.set_detail_path(meta.current_path.clone().unwrap_or_default().into());
        w.set_detail_preview(preview.unwrap_or_default());
        w.set_detail_has_preview(has_preview);
        w.set_detail_tab("metadata".into());
        w.set_detail_loaded(true);
        set_status(&w, "image detail loaded");
    }
    DETAIL_CACHE.with(|slot| {
        *slot.borrow_mut() = Some(forza_app::ImageDetailData {
            meta,
            laps,
            reviews,
            results,
            attempts,
        });
    });
}

/// Apply a settings load/preview/save outcome to the page and dependent UI.
pub(crate) fn apply_settings(
    ui: &slint::Weak<MainWindow>,
    outcome: crate::worker::SettingsOutcome,
) {
    SETTINGS_MODEL.with(|slot| {
        if let Some(model) = slot.borrow().as_ref() {
            let items: Vec<SettingItem> = outcome
                .snapshot
                .rows
                .iter()
                .map(|r| SettingItem {
                    key: r.key.clone().into(),
                    name: r.name.clone().into(),
                    value: r.value.clone().into(),
                    status: r.status.clone().into(),
                    editor: r.editor.clone().into(),
                    options: r.options.join("; ").into(),
                    group: r.group.into(),
                })
                .collect();
            model.set_vec(items);
        }
    });

    if !outcome.snapshot.dirty {
        // Load or successful save: the pending set is fully incorporated.
        PENDING_SETTINGS.with(|slot| slot.borrow_mut().clear());
    }

    if let Some(w) = ui.upgrade() {
        w.set_settings_valid(outcome.snapshot.validation_ok);
        w.set_settings_validation_text(outcome.snapshot.validation_message.clone().into());
        w.set_settings_dirty(outcome.snapshot.dirty);
        if !outcome.message.is_empty() {
            w.set_settings_message(outcome.message.clone().into());
            set_status(&w, &outcome.message);
        }
        if outcome.gamertag_recomputed {
            GAMERTAG.with(|slot| *slot.borrow_mut() = outcome.config.gamertag.clone());
            w.set_context_gamertag(outcome.config.gamertag.clone().into());
            w.set_run_info(run_info_line(&outcome.config).into());
            set_status(&w, "gamertag changed; best laps recomputed");
            send_request(Request::ListBestLaps);
            send_request(Request::ListReviews {
                bucket: "open".into(),
            });
            send_request(Request::RefreshInventory {
                filter: ImageInventoryFilter::default(),
            });
        }
    }
    RUN_CONFIG.with(|slot| {
        *slot.borrow_mut() = Some(forza_app::RunParams::from_config(&outcome.config, false));
    });
}

pub(crate) fn apply_debug_cases(
    ui: &slint::Weak<MainWindow>,
    result: Result<Vec<forza_db::image_debug::ImageDebugCase>, String>,
) {
    match result {
        Ok(cases) => {
            let count = cases.len();
            DEBUG_CASES_CACHE.with(|slot| *slot.borrow_mut() = cases.clone());
            DEBUG_CASE_MODEL.with(|slot| {
                if let Some(model) = slot.borrow().as_ref() {
                    let items: Vec<DebugCaseItem> = cases
                        .iter()
                        .map(|c| DebugCaseItem {
                            image_file_id: c.image_file_id.clone().into(),
                            image_name: c.image_name.clone().into(),
                            file_status: c.file_status.clone().into(),
                            processing: c.processing_status.clone().into(),
                            best_lap: c.best_lap_status.clone().into(),
                            latest_status: c
                                .latest_result_status
                                .clone()
                                .unwrap_or_else(|| "—".into())
                                .into(),
                            run_id: c.run_id.clone().unwrap_or_default().into(),
                            model: c.model.clone().unwrap_or_default().into(),
                            attempts: c.attempt_count as i32,
                            laps: c.lap_count as i32,
                            reviews: c.review_count as i32,
                        })
                        .collect();
                    model.set_vec(items);
                }
            });
            if let Some(w) = ui.upgrade() {
                w.set_status_text(format!("{count} debug case(s)").into());
            }
        }
        Err(message) => {
            if let Some(w) = ui.upgrade() {
                w.set_status_text(format!("error: {message}").into());
            }
        }
    }
}

pub(crate) fn apply_debug_detail(
    ui: &slint::Weak<MainWindow>,
    detail: forza_db::image_debug::ImageDebugDetail,
) {
    DEBUG_DETAIL_CACHE.with(|slot| *slot.borrow_mut() = Some(detail.clone()));
    DEBUG_RESULT_MODEL.with(|slot| {
        if let Some(model) = slot.borrow().as_ref() {
            let items: Vec<DebugResultComboItem> = detail
                .results
                .iter()
                .map(|r| DebugResultComboItem {
                    id: r.id.clone().into(),
                    label: format!(
                        "{} · {} · {}",
                        r.status,
                        r.run_id,
                        r.created_at.clone().unwrap_or_else(|| "—".into())
                    )
                    .into(),
                })
                .collect();
            model.set_vec(items);
        }
    });
    let labels: Vec<slint::SharedString> = detail
        .results
        .iter()
        .map(|r| {
            format!(
                "{} · {} · {}",
                r.status,
                r.run_id,
                r.created_at.clone().unwrap_or_else(|| "—".into())
            )
            .into()
        })
        .collect();

    // Build tab texts (mirrors Python image_debug_view helpers, simplified).
    let overview = format!(
        "Image: {}\nFile: {} · Process: {} · Best lap: {}\nSelected result: {}\nAttempts: {} · Laps: {} · Reviews: {}\nRaw evidence: {}\n",
        detail.image_name,
        detail
            .cases
            .first()
            .map(|c| c.file_status.as_str())
            .unwrap_or("—"),
        detail
            .cases
            .first()
            .map(|c| c.processing_status.as_str())
            .unwrap_or("—"),
        detail
            .cases
            .first()
            .map(|c| c.best_lap_status.as_str())
            .unwrap_or("—"),
        detail
            .selected_result_id
            .clone()
            .unwrap_or_else(|| "—".into()),
        detail.attempts.len(),
        detail.laps.len(),
        detail.reviews.len(),
        if detail.raw_response.is_some() {
            "present"
        } else {
            "missing"
        }
    );
    let metadata = {
        let case = detail.cases.first();
        format!(
            "id: {}\nname: {}\nfile: {} · best: {}\nlatest: {} · run: {}\nmodel: {}\n",
            detail.image_file_id,
            detail.image_name,
            case.map(|c| c.file_status.as_str()).unwrap_or("—"),
            case.map(|c| c.best_lap_status.as_str()).unwrap_or("—"),
            case.and_then(|c| c.latest_result_status.clone())
                .unwrap_or_else(|| "—".into()),
            case.and_then(|c| c.run_id.clone())
                .unwrap_or_else(|| "—".into()),
            case.and_then(|c| c.model.clone())
                .unwrap_or_else(|| "—".into()),
        )
    };
    let results_text = if detail.results.is_empty() {
        "No extraction results.".into()
    } else {
        detail
            .results
            .iter()
            .map(|r| {
                format!(
                    "{} · {} · run={} · model={} · attempts={} · error={} · id={}",
                    r.created_at.clone().unwrap_or_else(|| "—".into()),
                    r.status,
                    r.run_id,
                    r.model.clone().unwrap_or_else(|| "—".into()),
                    r.attempt_count,
                    r.error_message.clone().unwrap_or_else(|| "—".into()),
                    r.id
                )
            })
            .collect::<Vec<_>>()
            .join("\n")
    };
    let attempts_text = if detail.attempts.is_empty() {
        "No attempts for the selected result.".into()
    } else {
        detail
            .attempts
            .iter()
            .map(|a| {
                format!(
                    "#{} · {} · reason={} · model={} · duration={} ms · tps={}",
                    a.attempt_number,
                    if a.accepted {
                        "accepted"
                    } else {
                        a.status.as_str()
                    },
                    a.attempt_reason,
                    a.model.clone().unwrap_or_else(|| "—".into()),
                    a.duration_ms
                        .map(|v| v.to_string())
                        .unwrap_or_else(|| "—".into()),
                    a.tokens_per_second
                        .map(|v| format!("{v:.1}"))
                        .unwrap_or_else(|| "—".into()),
                )
            })
            .collect::<Vec<_>>()
            .join("\n")
    };
    let laps_reviews = {
        let mut lines = vec!["Laps".to_string()];
        if detail.laps.is_empty() {
            lines.push("No laps.".into());
        } else {
            for lap in &detail.laps {
                let flags = match (lap.dirty, lap.is_best_lap) {
                    (true, true) => "dirty/best",
                    (true, false) => "dirty",
                    (false, true) => "best",
                    _ => "clean",
                };
                lines.push(format!(
                    "#{} · {} · {} · {} · {} · {} · {}",
                    lap.lap_index,
                    lap.track,
                    lap.race_class,
                    lap.driver,
                    lap.car,
                    lap.best_lap,
                    flags
                ));
            }
        }
        lines.push(String::new());
        lines.push("Reviews".to_string());
        if detail.reviews.is_empty() {
            lines.push("No review cases.".into());
        } else {
            for rev in &detail.reviews {
                lines.push(format!(
                    "#{} · {} · {} · outcome={} · field={} · model={}",
                    rev.case_number,
                    rev.status,
                    rev.reason,
                    rev.outcome,
                    rev.decision_field.clone().unwrap_or_else(|| "—".into()),
                    rev.model_value.clone().unwrap_or_else(|| "—".into()),
                ));
            }
        }
        lines.join("\n")
    };

    if let Some(w) = ui.upgrade() {
        w.set_debug_title(detail.image_name.clone().into());
        w.set_debug_selected_image_id(detail.image_file_id.clone().into());
        w.set_debug_selected_result_id(
            detail.selected_result_id.clone().unwrap_or_default().into(),
        );
        w.set_debug_result_labels(ModelRc::new(VecModel::from(labels)));
        w.set_debug_tab("overview".into());
        w.set_debug_overview_text(overview.into());
        w.set_debug_metadata_text(metadata.into());
        w.set_debug_results_text(results_text.into());
        w.set_debug_attempts_text(attempts_text.into());
        w.set_debug_response_text(
            detail
                .raw_response
                .clone()
                .unwrap_or_else(|| "—".into())
                .into(),
        );
        w.set_debug_parsed_text(
            detail
                .parsed_json
                .clone()
                .unwrap_or_else(|| "—".into())
                .into(),
        );
        w.set_debug_laps_reviews_text(laps_reviews.into());
        w.set_debug_timeline_text(detail.timeline.join("\n").into());
        w.set_status_text("debug detail loaded".into());
    }
}
