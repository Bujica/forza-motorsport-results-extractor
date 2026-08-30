//! Best Laps: frontier + external records, cascading filters, output helpers.

use std::collections::{BTreeSet, HashSet};

use rusqlite::Connection;

use forza_db::repositories::external_records::ExternalLapRecord;
use forza_domain::lap::strip_dirty_symbol;
use forza_domain::ordering::{LapRowLike, ordered_lap_key, track_order_map};

/// One row in the Best Laps view (internal or external).
#[derive(Debug, Clone, PartialEq)]
pub struct BestLapRow {
    pub lap_id: Option<String>,
    pub image_file_id: Option<String>,
    pub run_id: Option<String>,
    pub track: String,
    pub race_class: String,
    pub weather: String,
    pub temp_f: Option<f64>,
    pub temp_c: Option<f64>,
    pub driver: String,
    pub car: String,
    pub car_class: String,
    pub best_lap: String,
    pub best_lap_ms: i64,
    pub dirty: bool,
    pub source_file: String,
    pub source_type: String,
    pub source_label: String,
    pub is_external: bool,
}

impl LapRowLike for BestLapRow {
    fn track(&self) -> &str {
        &self.track
    }
    fn race_class(&self) -> &str {
        &self.race_class
    }
    fn weather(&self) -> Option<&str> {
        Some(&self.weather)
    }
    fn best_lap_ms(&self) -> i64 {
        self.best_lap_ms
    }
    fn driver(&self) -> &str {
        &self.driver
    }
    fn car(&self) -> &str {
        &self.car
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct BestLapFilter {
    pub track: Option<String>,
    pub race_class: Option<String>,
    pub weather: Option<String>,
    pub driver: Option<String>,
    pub car: Option<String>,
    /// "all" | "clean" | "dirty"
    pub dirty: String,
    /// "all" | "screenshots" | "external"
    pub source: String,
    pub only_mine: bool,
}

impl BestLapFilter {
    #[allow(clippy::too_many_arguments)]
    pub fn from_strings(
        track: &str,
        race_class: &str,
        weather: &str,
        driver: &str,
        car: &str,
        dirty: &str,
        source: &str,
        only_mine: bool,
    ) -> Self {
        Self {
            track: none_for_all(track),
            race_class: none_for_all(race_class),
            weather: none_for_all(weather),
            driver: none_for_all(driver),
            car: none_for_all(car),
            dirty: if dirty.is_empty() {
                "all".to_string()
            } else {
                dirty.to_string()
            },
            source: if source.is_empty() {
                "all".to_string()
            } else {
                source.to_string()
            },
            only_mine,
        }
    }
}

fn none_for_all(value: &str) -> Option<String> {
    if value.is_empty() || value == "all" {
        None
    } else {
        Some(value.to_string())
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct BestLapFilterOptions {
    pub tracks: Vec<String>,
    pub race_classes: Vec<String>,
    pub weather: Vec<String>,
    pub drivers: Vec<String>,
    pub cars: Vec<String>,
    pub dirty_states: Vec<String>,
    pub source_states: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BestLapSummary {
    pub tracks: usize,
    pub clean: usize,
    pub dirty: usize,
    pub screenshots: usize,
    pub external: usize,
}

fn row_from_export(row: forza_db::repositories::ExportFlatRow) -> BestLapRow {
    let best_lap = row.best_lap.clone().unwrap_or_default();
    let best_lap_ms = row.best_lap_ms.unwrap_or(i64::MAX);
    let source_file = row.source_file.clone().unwrap_or_default();
    BestLapRow {
        lap_id: None,
        image_file_id: None,
        run_id: None,
        track: row.track.clone(),
        race_class: row.race_class.clone(),
        car_class: row.race_class.clone(),
        weather: row.weather.unwrap_or_else(|| "unknown".to_string()),
        temp_f: row.temp_f,
        temp_c: row.temp_c,
        driver: row.driver.clone(),
        car: row.car.clone(),
        best_lap,
        best_lap_ms,
        dirty: row.dirty,
        source_file: source_file.clone(),
        source_type: "internal".to_string(),
        source_label: source_file,
        is_external: false,
    }
}

fn row_from_external(rec: ExternalLapRecord) -> BestLapRow {
    BestLapRow {
        lap_id: None,
        image_file_id: None,
        run_id: None,
        track: rec.track.clone(),
        race_class: rec.race_class.clone(),
        car_class: rec.race_class.clone(),
        weather: "dry".to_string(),
        temp_f: None,
        temp_c: None,
        driver: rec.driver.clone(),
        car: rec.car.clone(),
        best_lap: rec.best_lap.clone(),
        best_lap_ms: rec.best_lap_ms,
        dirty: false,
        source_file: rec.source.clone(),
        source_type: "external".to_string(),
        source_label: rec.source.clone(),
        is_external: true,
    }
}

/// Load all best-lap rows (internal frontier + active external), sorted per domain ordering.
pub fn list_best_laps(conn: &Connection, gamertag_lower: &str) -> Result<Vec<BestLapRow>, String> {
    let internal = forza_db::repositories::laps::list_clean_flat(conn, gamertag_lower)
        .map_err(|e| e.to_string())?;
    let mut rows: Vec<BestLapRow> = internal.into_iter().map(row_from_export).collect();
    // External records are always ordered deterministically via SQL; they join the frontier.
    let external = forza_db::repositories::external_records::list_active_external_records(conn)
        .map_err(|e| e.to_string())?;
    rows.extend(external.into_iter().map(row_from_external));
    // Python sorts via ordered_lap_key across all rows (track canonical -> class -> weather -> time -> driver -> car).
    // Track canonical order is not available without config; for now alphabetical with domain helper (empty order map).
    // Keep same order as Python's BestLapsController uses ordered_lap_key with empty {} then grouped; preserve time ordering within track/class buckets.
    let order_map = track_order_map(&[]);
    rows.sort_by_key(|a| ordered_lap_key(a, &order_map));
    Ok(rows)
}

fn is_mine(row: &BestLapRow, gamertag_lower: &str) -> bool {
    !gamertag_lower.is_empty() && row.driver.trim().to_lowercase() == gamertag_lower
}

pub fn apply_filters(
    rows: &[BestLapRow],
    filter: &BestLapFilter,
    gamertag_lower: &str,
    exclude: Option<&str>,
) -> Vec<BestLapRow> {
    rows.iter()
        .filter(|row| {
            if exclude != Some("track")
                && let Some(v) = &filter.track
                && &row.track != v
            {
                return false;
            }
            if exclude != Some("race_class")
                && let Some(v) = &filter.race_class
                && &row.race_class != v
            {
                return false;
            }
            if exclude != Some("weather")
                && let Some(v) = &filter.weather
                && &row.weather != v
            {
                return false;
            }
            if exclude != Some("driver")
                && let Some(v) = &filter.driver
                && &row.driver != v
            {
                return false;
            }
            if exclude != Some("car")
                && let Some(v) = &filter.car
                && &row.car != v
            {
                return false;
            }
            if exclude != Some("dirty") {
                match filter.dirty.as_str() {
                    "clean" if row.dirty => return false,
                    "dirty" if !row.dirty => return false,
                    _ => {}
                }
            }
            if exclude != Some("source") {
                match filter.source.as_str() {
                    "screenshots" if row.is_external => return false,
                    "external" if !row.is_external => return false,
                    _ => {}
                }
            }
            if filter.only_mine && !is_mine(row, gamertag_lower) {
                return false;
            }
            true
        })
        .cloned()
        .collect()
}

fn unique_sorted(values: impl Iterator<Item = String>) -> Vec<String> {
    let set: BTreeSet<String> = values.filter(|v| !v.is_empty()).collect();
    set.into_iter().collect()
}

fn dirty_options(rows: &[BestLapRow]) -> Vec<String> {
    let mut states = HashSet::new();
    for r in rows {
        states.insert(if r.dirty { "dirty" } else { "clean" });
    }
    let mut out = Vec::new();
    for s in ["clean", "dirty"] {
        if states.contains(s) {
            out.push(s.to_string());
        }
    }
    out
}

fn source_options(rows: &[BestLapRow]) -> Vec<String> {
    let mut states = HashSet::new();
    for r in rows {
        states.insert(if r.is_external {
            "external"
        } else {
            "screenshots"
        });
    }
    let mut out = Vec::new();
    for s in ["screenshots", "external"] {
        if states.contains(s) {
            out.push(s.to_string());
        }
    }
    out
}

pub fn filter_options(
    all_rows: &[BestLapRow],
    filter: &BestLapFilter,
    gamertag_lower: &str,
) -> BestLapFilterOptions {
    BestLapFilterOptions {
        tracks: unique_sorted(
            apply_filters(all_rows, filter, gamertag_lower, Some("track"))
                .into_iter()
                .map(|r| r.track),
        ),
        race_classes: unique_sorted(
            apply_filters(all_rows, filter, gamertag_lower, Some("race_class"))
                .into_iter()
                .map(|r| r.race_class),
        ),
        weather: unique_sorted(
            apply_filters(all_rows, filter, gamertag_lower, Some("weather"))
                .into_iter()
                .map(|r| r.weather),
        ),
        drivers: unique_sorted(
            apply_filters(all_rows, filter, gamertag_lower, Some("driver"))
                .into_iter()
                .map(|r| r.driver),
        ),
        cars: unique_sorted(
            apply_filters(all_rows, filter, gamertag_lower, Some("car"))
                .into_iter()
                .map(|r| r.car),
        ),
        dirty_states: dirty_options(&apply_filters(
            all_rows,
            filter,
            gamertag_lower,
            Some("dirty"),
        )),
        source_states: source_options(&apply_filters(
            all_rows,
            filter,
            gamertag_lower,
            Some("source"),
        )),
    }
}

pub fn summary(rows: &[BestLapRow], only_mine: bool) -> BestLapSummary {
    let tracks = rows.iter().map(|r| &r.track).collect::<HashSet<_>>().len();
    let clean = rows.iter().filter(|r| !r.dirty).count();
    let dirty = rows.len() - clean;
    let external = rows.iter().filter(|r| r.is_external).count();
    let screenshots = rows.len() - external;
    let _ = only_mine;
    BestLapSummary {
        tracks,
        clean,
        dirty,
        screenshots,
        external,
    }
}

pub fn summary_text(summary: &BestLapSummary, only_mine: bool) -> String {
    let player = if only_mine {
        " · Only this driver"
    } else {
        ""
    };
    format!(
        "Tracks: {} · Clean: {} · Dirty: {} · Screenshots: {} · External: {}{}",
        summary.tracks, summary.clean, summary.dirty, summary.screenshots, summary.external, player
    )
}

/// CSV row mapping mirrors `best_laps_controller.py:_csv_row`.
pub fn csv_row(row: &BestLapRow) -> std::collections::BTreeMap<String, String> {
    let mut map = std::collections::BTreeMap::new();
    map.insert("track".to_string(), row.track.clone());
    map.insert("race_class".to_string(), row.race_class.clone());
    map.insert("weather".to_string(), row.weather.clone());
    map.insert(
        "temp_f".to_string(),
        row.temp_f.map(fmt_float).unwrap_or_default(),
    );
    map.insert("driver".to_string(), row.driver.clone());
    map.insert("car".to_string(), row.car.clone());
    map.insert("car_class".to_string(), row.car_class.clone());
    map.insert("best_lap".to_string(), strip_dirty_symbol(&row.best_lap));
    map.insert("best_lap_ms".to_string(), row.best_lap_ms.to_string());
    map.insert("dirty".to_string(), row.dirty.to_string());
    map.insert(
        "source".to_string(),
        if row.source_label.is_empty() {
            row.source_file.clone()
        } else {
            row.source_label.clone()
        },
    );
    map.insert("source_type".to_string(), row.source_type.clone());
    map.insert("source_file".to_string(), row.source_file.clone());
    map.insert(
        "image_file_id".to_string(),
        row.image_file_id.clone().unwrap_or_default(),
    );
    map.insert("lap_id".to_string(), row.lap_id.clone().unwrap_or_default());
    map.insert("run_id".to_string(), row.run_id.clone().unwrap_or_default());
    map
}

fn fmt_float(v: f64) -> String {
    if v == v.trunc() && v.abs() < 1e15 {
        format!("{v:.1}")
    } else {
        format!("{v}")
    }
}

/// Build ExportRow slices for CSV/PDF consumers.
pub fn to_export_rows(rows: &[BestLapRow]) -> Vec<forza_output::csv::ExportRow> {
    rows.iter()
        .map(|r| forza_output::csv::ExportRow {
            track: r.track.clone(),
            race_class: r.race_class.clone(),
            weather: Some(r.weather.clone()),
            temp_f: r.temp_f,
            temp_c: r.temp_c,
            driver: r.driver.clone(),
            car: r.car.clone(),
            best_lap: Some(strip_dirty_symbol(&r.best_lap)),
            best_lap_ms: Some(r.best_lap_ms),
            dirty: r.dirty,
            source_file: Some(if r.source_label.is_empty() {
                r.source_file.clone()
            } else {
                r.source_label.clone()
            }),
            race_date: None,
            image_format: None,
            width_px: None,
            height_px: None,
        })
        .collect()
}

pub fn to_external_pdf_records(rows: &[BestLapRow]) -> Vec<forza_output::pdf::PdfExternalRecord> {
    rows.iter()
        .filter(|r| r.is_external)
        .map(|r| forza_output::pdf::PdfExternalRecord {
            track: r.track.clone(),
            race_class: r.race_class.clone(),
            driver: r.driver.clone(),
            car: r.car.clone(),
            best_lap: strip_dirty_symbol(&r.best_lap),
            best_lap_ms: r.best_lap_ms,
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn row(
        track: &str,
        class: &str,
        driver: &str,
        car: &str,
        ms: i64,
        dirty: bool,
        external: bool,
    ) -> BestLapRow {
        BestLapRow {
            lap_id: None,
            image_file_id: None,
            run_id: None,
            track: track.to_string(),
            race_class: class.to_string(),
            weather: "dry".to_string(),
            temp_f: Some(80.0),
            temp_c: Some(26.7),
            driver: driver.to_string(),
            car: car.to_string(),
            car_class: class.to_string(),
            best_lap: format!("1:{:02}.000", ms / 1000 % 60),
            best_lap_ms: ms,
            dirty,
            source_file: "file.png".to_string(),
            source_type: if external {
                "external".to_string()
            } else {
                "internal".to_string()
            },
            source_label: "file.png".to_string(),
            is_external: external,
        }
    }

    #[test]
    fn cascading_filters_exclude_self() {
        let rows = vec![
            row("Laguna Seca", "A", "Alice", "Car A", 90_000, false, false),
            row("Fuji", "B", "Bob", "Car B", 91_000, true, false),
            row("Fuji", "A", "Alice", "Car C", 89_000, false, true),
        ];
        let filter = BestLapFilter {
            track: Some("Fuji".to_string()),
            ..Default::default()
        };
        // tracks options should include Laguna Seca even though filter excludes it (exclude=self).
        let opts = filter_options(&rows, &filter, "");
        assert!(opts.tracks.contains(&"Laguna Seca".to_string()));
        assert!(opts.tracks.contains(&"Fuji".to_string()));
        // applying filter without exclude should yield only Fuji rows.
        let filtered = apply_filters(&rows, &filter, "", None);
        assert_eq!(filtered.len(), 2);
    }

    #[test]
    fn dirty_and_source_filters() {
        let rows = vec![
            row("T", "A", "D", "C", 90_000, false, false),
            row("T", "A", "D", "C", 91_000, true, false),
            row("T", "A", "D", "C", 89_000, false, true),
        ];
        let f = BestLapFilter {
            dirty: "clean".to_string(),
            ..Default::default()
        };
        assert_eq!(apply_filters(&rows, &f, "", None).len(), 2);
        let f2 = BestLapFilter {
            source: "external".to_string(),
            ..Default::default()
        };
        assert_eq!(apply_filters(&rows, &f2, "", None).len(), 1);
    }
}
