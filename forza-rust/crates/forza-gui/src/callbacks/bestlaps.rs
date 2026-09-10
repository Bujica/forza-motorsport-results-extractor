//! Best-laps wiring.

use std::path::Path;
use std::rc::Rc;

use slint::{ComponentHandle, ModelRc, VecModel};

use crate::ui_state::{
    BESTLAP_ALL, BESTLAP_FILTER, BESTLAP_MODEL, BESTLAP_SORT, CONFIG_PATH, GAMERTAG, enqueue,
    set_status,
};
use crate::worker::Request;
use crate::{BestLapItem, MainWindow};

pub(super) fn apply_bestlaps_filters(ui: &MainWindow) {
    let gamertag_lower = GAMERTAG.with(|s| s.borrow().clone().to_lowercase());
    let (all_rows, filter, sort) = (
        BESTLAP_ALL.with(|s| s.borrow().clone()),
        BESTLAP_FILTER.with(|s| s.borrow().clone()),
        BESTLAP_SORT.with(|s| *s.borrow()),
    );
    let mut filtered = forza_app::apply_filters(&all_rows, &filter, &gamertag_lower, None);
    // Domain ordering (Python): track canonical -> class -> weather -> time -> driver -> car
    // Header sort overrides it only when user explicitly clicks a column; default (99) keeps domain order.
    let track_order = forza_domain::reference_data::embedded_reference_data().tracks;
    let order_map = forza_domain::ordering::track_order_map(&track_order);
    if sort.0 <= 3 {
        filtered.sort_by(|a, b| {
            let ord = match sort.0 {
                0 => a.driver.to_lowercase().cmp(&b.driver.to_lowercase()),
                1 => a.car.to_lowercase().cmp(&b.car.to_lowercase()),
                2 => a.best_lap_ms.cmp(&b.best_lap_ms),
                3 => a.weather.to_lowercase().cmp(&b.weather.to_lowercase()),
                _ => std::cmp::Ordering::Equal,
            };
            let ord = if ord == std::cmp::Ordering::Equal {
                forza_domain::ordering::ordered_lap_key(a, &order_map)
                    .cmp(&forza_domain::ordering::ordered_lap_key(b, &order_map))
            } else {
                ord
            };
            if sort.1 { ord } else { ord.reverse() }
        });
    } else {
        // Default: preserve Python's ordered_lap_key ordering (all_rows already sorted, but re-sort to guarantee stability after filters).
        filtered.sort_by_key(|a| forza_domain::ordering::ordered_lap_key(a, &order_map));
    }
    let summary = forza_app::summary(&filtered, filter.only_mine);
    ui.set_best_laps_summary(forza_app::summary_text(&summary, filter.only_mine).into());
    ui.set_best_laps_sort_column(sort.0 as i32);
    ui.set_best_laps_sort_ascending(sort.1);
    // Filter option models (cascade: exclude self)
    let options = forza_app::filter_options(&all_rows, &filter, &gamertag_lower);
    let to_model = |values: Vec<String>| -> ModelRc<slint::SharedString> {
        let mut with_all = vec!["all".into()];
        with_all.extend(values.into_iter().map(|v| v.into()));
        ModelRc::from(Rc::new(VecModel::from(with_all)))
    };
    ui.set_best_laps_tracks(to_model(options.tracks));
    ui.set_best_laps_classes(to_model(options.race_classes));
    ui.set_best_laps_weathers(to_model(options.weather));
    ui.set_best_laps_drivers(to_model(options.drivers));
    ui.set_best_laps_cars(to_model(options.cars));
    ui.set_best_laps_sources({
        let mut vals = options.source_states;
        if vals.is_empty() {
            vals = vec!["screenshots".to_string(), "external".to_string()];
        }
        let mut with_all = vec!["all".into()];
        with_all.extend(vals.into_iter().map(|v| v.into()));
        ModelRc::from(Rc::new(VecModel::from(with_all)))
    });
    ui.set_best_laps_laps({
        let mut vals = options.dirty_states;
        if vals.is_empty() {
            vals = vec!["clean".to_string(), "dirty".to_string()];
        }
        let mut with_all = vec!["all".into()];
        with_all.extend(vals.into_iter().map(|v| v.into()));
        ModelRc::from(Rc::new(VecModel::from(with_all)))
    });
    // Build grouped display list: group header + rows.
    let mut counts: std::collections::HashMap<(String, String), usize> =
        std::collections::HashMap::new();
    for r in &filtered {
        *counts
            .entry((r.track.clone(), r.race_class.clone()))
            .or_insert(0) += 1;
    }
    let mut items: Vec<BestLapItem> = Vec::new();
    let mut current_key: Option<(String, String)> = None;
    for r in &filtered {
        let key = (r.track.clone(), r.race_class.clone());
        if current_key.as_ref() != Some(&key) {
            let cnt = *counts.get(&key).unwrap_or(&0) as i32;
            items.push(BestLapItem {
                track: r.track.clone().into(),
                class: r.race_class.clone().into(),
                driver: "".into(),
                car: "".into(),
                time: "".into(),
                weather: "".into(),
                temp: "".into(),
                source: "".into(),
                dirty: false,
                mine: false,
                external: false,
                is_group: true,
                group_count: cnt,
                image_file_id: "".into(),
            });
            current_key = Some(key);
        }
        let is_mine = !gamertag_lower.is_empty() && r.driver.to_lowercase() == gamertag_lower;
        items.push(BestLapItem {
            track: r.track.clone().into(),
            class: r.race_class.clone().into(),
            driver: r.driver.clone().into(),
            car: r.car.clone().into(),
            time: r.best_lap.clone().into(),
            weather: r.weather.clone().into(),
            temp: r
                .temp_f
                .map(|v| format!("{v:.0}°F"))
                .unwrap_or_default()
                .into(),
            source: if r.is_external {
                r.source_label.clone().into()
            } else {
                "screenshots".into()
            },
            dirty: r.dirty,
            mine: is_mine,
            external: r.is_external,
            is_group: false,
            group_count: 0,
            image_file_id: r.image_file_id.clone().unwrap_or_default().into(),
        });
    }
    BESTLAP_MODEL.with(|slot| {
        if let Some(model) = slot.borrow().as_ref() {
            model.set_vec(items);
        }
    });
}

/// Wire the Best-laps callbacks.
pub(crate) fn wire_bestlaps(main: &MainWindow) {
    {
        let ui = main.as_weak();
        main.on_bestlaps_requested(move || {
            enqueue(Request::ListBestLaps, &ui, "loading best laps…");
        });
    }
    {
        let ui = main.as_weak();
        main.on_bestlaps_filter_changed(
            move |track, class, weather, driver, car, lap, source, only_mine| {
                BESTLAP_FILTER.with(|slot| {
                    *slot.borrow_mut() = forza_app::BestLapFilter::from_strings(
                        &track, &class, &weather, &driver, &car, &lap, &source, only_mine,
                    );
                });
                if let Some(w) = ui.upgrade() {
                    apply_bestlaps_filters(&w);
                }
            },
        );
    }
    {
        let ui = main.as_weak();
        main.on_bestlaps_sort_changed(move |col| {
            let Ok(col) = usize::try_from(col) else {
                return;
            };
            BESTLAP_SORT.with(|slot| {
                let mut state = slot.borrow_mut();
                let (cur_col, cur_asc) = *state;
                let asc = if cur_col == col { !cur_asc } else { true };
                *state = (col, asc);
            });
            if let Some(w) = ui.upgrade() {
                apply_bestlaps_filters(&w);
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_bestlaps_export_csv(move || {
            let Some(dest) = rfd::FileDialog::new()
                .set_title("Export best laps")
                .add_filter("CSV", &["csv"])
                .set_file_name("best_laps.csv")
                .save_file()
            else {
                return;
            };
            let rows = BESTLAP_ALL.with(|all| {
                let filter = BESTLAP_FILTER.with(|f| f.borrow().clone());
                let gamertag = GAMERTAG.with(|s| s.borrow().clone().to_lowercase());
                forza_app::apply_filters(&all.borrow(), &filter, &gamertag, None)
            });
            if rows.is_empty() {
                if let Some(w) = ui.upgrade() {
                    w.set_status_text("No best laps to export.".into());
                }
                return;
            }
            let export_rows = forza_app::to_export_rows(&rows);
            let result = forza_output::export_csv(&export_rows, &dest);
            if let Some(w) = ui.upgrade() {
                match result {
                    Ok(n) => w.set_status_text(
                        format!("Best laps exported: {n} row(s) · {}", dest.display()).into(),
                    ),
                    Err(e) => w.set_status_text(format!("Export failed: {e}").into()),
                }
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_bestlaps_generate_pdf(move || {
            let rows = BESTLAP_ALL.with(|all| {
                let filter = BESTLAP_FILTER.with(|f| f.borrow().clone());
                let gamertag = GAMERTAG.with(|s| s.borrow().clone().to_lowercase());
                forza_app::apply_filters(&all.borrow(), &filter, &gamertag, None)
            });
            if rows.is_empty() {
                if let Some(w) = ui.upgrade() {
                    w.set_status_text("No filtered best laps to generate PDF.".into());
                }
                return;
            }
            let config_path = CONFIG_PATH.with(|p| p.borrow().clone());
            let (cfg, _) = match forza_config::load_config(&config_path, false) {
                Ok(v) => v,
                Err(e) => {
                    if let Some(w) = ui.upgrade() {
                        w.set_status_text(format!("Config load failed: {}", e.message).into());
                    }
                    return;
                }
            };
            // Track order from embedded reference data (matches Python's reference catalog).
            let track_order: Vec<String> = forza_domain::reference_data::embedded_reference_data()
                .tracks
                .into_iter()
                .collect();
            let internal = rows
                .iter()
                .filter(|r| !r.is_external)
                .cloned()
                .collect::<Vec<_>>();
            let external = rows
                .iter()
                .filter(|r| r.is_external)
                .cloned()
                .collect::<Vec<_>>();
            let internal_export = forza_app::to_export_rows(&internal);
            let external_records = external
                .iter()
                .map(|r| forza_output::PdfExternalRecord {
                    track: r.track.clone(),
                    race_class: r.race_class.clone(),
                    driver: r.driver.clone(),
                    car: r.car.clone(),
                    best_lap: forza_domain::lap::strip_dirty_symbol(&r.best_lap),
                    best_lap_ms: r.best_lap_ms,
                })
                .collect::<Vec<_>>();
            let options = forza_output::PdfRenderOptions {
                show_dirty_symbol: cfg.pdf.show_dirty_lap_symbol,
                dirty_symbol: cfg.pdf.dirty_lap_symbol.clone(),
            };
            let plan = forza_output::build_pdf_plan_ext(
                &internal_export,
                &cfg.gamertag,
                &track_order,
                &external_records,
                options,
            );
            let pdf_path = config_path
                .parent()
                .unwrap_or_else(|| Path::new("."))
                .join(&cfg.pdf_file);
            match forza_output::render_pdf(&plan, &pdf_path) {
                Ok(_) => {
                    if let Some(w) = ui.upgrade() {
                        w.set_status_text(
                            format!(
                                "Filtered PDF generated: {} row(s) · {}",
                                rows.len(),
                                pdf_path.display()
                            )
                            .into(),
                        );
                    }
                    let _ = opener::open(&pdf_path);
                }
                Err(e) => {
                    if let Some(w) = ui.upgrade() {
                        w.set_status_text(format!("PDF generation failed: {e}").into());
                    }
                }
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_bestlaps_open_pdf(move || {
            let config_path = CONFIG_PATH.with(|p| p.borrow().clone());
            let (cfg, _) = match forza_config::load_config(&config_path, false) {
                Ok(v) => v,
                Err(e) => {
                    if let Some(w) = ui.upgrade() {
                        w.set_status_text(format!("Config load failed: {}", e.message).into());
                    }
                    return;
                }
            };
            let pdf_path = config_path
                .parent()
                .unwrap_or_else(|| Path::new("."))
                .join(&cfg.pdf_file);
            if !pdf_path.exists() {
                if let Some(w) = ui.upgrade() {
                    w.set_status_text(format!("PDF not found: {}", pdf_path.display()).into());
                }
                return;
            }
            let _ = opener::open(&pdf_path);
            if let Some(w) = ui.upgrade() {
                w.set_status_text(format!("Opened PDF: {}", pdf_path.display()).into());
            }
        });
    }
    {
        let ui = main.as_weak();
        main.on_bestlaps_import(move || {
            let Some(path) = rfd::FileDialog::new()
                .set_title("Import external records")
                .add_filter("Spreadsheets", &["xlsx", "csv"])
                .pick_file()
            else {
                return;
            };
            enqueue(
                Request::ImportExternalRecords {
                    path: path.to_string_lossy().to_string(),
                },
                &ui,
                "importing external records…",
            );
        });
    }
    {
        let ui = main.as_weak();
        main.on_bestlaps_detail_requested(move |image_file_id| {
            if image_file_id.is_empty() {
                return;
            }
            if let Some(w) = ui.upgrade() {
                w.set_page("image-detail".into());
                w.set_detail_loaded(false);
                set_status(&w, "loading image detail…");
            }
            enqueue(
                Request::LoadImageDetail {
                    image_id: image_file_id.to_string(),
                },
                &ui,
                "loading image detail…",
            );
        });
    }
}
