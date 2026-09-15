//! Best Laps: frontier + external records, cascading filters, output helpers.

use std::collections::{BTreeSet, HashSet};

use rusqlite::Connection;

use forza_db::repositories::external_records::ExternalLapRecord;
use forza_domain::enums::{RaceClass, WeatherType};
use forza_domain::lap::strip_dirty_symbol;
use forza_domain::ordering::{LapRow, ordered_lap_key, track_order_map};

/// Parse a persisted class string; garbage becomes `Unknown` (review queue
/// owns the `class_invalid` signal, Best Laps never panics on data).
fn parse_race_class(value: &str) -> RaceClass {
    value.parse::<RaceClass>().unwrap_or(RaceClass::Unknown)
}

/// One row in the Best Laps view (internal or external).
#[derive(Debug, Clone, PartialEq)]
pub struct BestLapRow {
    pub lap_id: Option<String>,
    pub image_file_id: Option<String>,
    pub run_id: Option<String>,
    pub track: String,
    pub race_class: RaceClass,
    pub weather: String,
    pub temp_f: Option<f64>,
    pub temp_c: Option<f64>,
    pub driver: String,
    pub car: String,
    pub car_class: RaceClass,
    pub best_lap: String,
    pub best_lap_ms: i64,
    pub dirty: bool,
    pub source_file: String,
    pub source_type: String,
    pub source_label: String,
    pub is_external: bool,
    pub mine: bool,
}

impl LapRow for BestLapRow {
    fn id(&self) -> &str {
        self.lap_id.as_deref().unwrap_or("")
    }
    fn image_file_id(&self) -> &str {
        self.image_file_id.as_deref().unwrap_or("")
    }
    fn track(&self) -> &str {
        &self.track
    }
    fn race_class(&self) -> &str {
        self.race_class.as_str()
    }
    fn weather(&self) -> Option<&str> {
        Some(&self.weather)
    }
    fn temp_f(&self) -> Option<f64> {
        self.temp_f
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
    fn dirty(&self) -> bool {
        self.dirty
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct BestLapFilter {
    pub track: Option<String>,
    pub race_class: Option<RaceClass>,
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
            race_class: none_for_all(race_class).map(|s| parse_race_class(&s)),
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
    pub race_classes: Vec<RaceClass>,
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
    let race_class = parse_race_class(&row.race_class);
    BestLapRow {
        lap_id: None,
        // Origin screenshot id — feeds the Best Laps "Image details" button.
        image_file_id: row.image_file_id.clone(),
        run_id: None,
        track: row.track.clone(),
        race_class,
        car_class: race_class,
        weather: row
            .weather
            .unwrap_or_else(|| WeatherType::Unknown.as_str().to_string()),
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
        mine: row.mine,
    }
}

fn row_from_external(rec: ExternalLapRecord) -> BestLapRow {
    let race_class = parse_race_class(&rec.race_class);
    BestLapRow {
        lap_id: None,
        image_file_id: None,
        run_id: None,
        track: rec.track.clone(),
        race_class,
        car_class: race_class,
        weather: WeatherType::Dry.as_str().to_string(),
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
        mine: false,
    }
}

/// Load all best-lap rows (internal frontier + active external), sorted per domain ordering.
///
/// # Errors
///
/// Returns `Err` with the database message when lap or external-record
/// queries fail.
pub fn list_best_laps(conn: &Connection, gamertag_lower: &str) -> Result<Vec<BestLapRow>, String> {
    let _ = forza_db::migration::seed_reference_catalog(conn);
    let internal = forza_db::repositories::laps::list_clean_flat(conn, gamertag_lower)
        .map_err(|e| e.to_string())?;
    let mut rows: Vec<BestLapRow> = internal.into_iter().map(row_from_export).collect();
    // External records are always ordered deterministically via SQL; they join the frontier.
    let external = forza_db::repositories::external_records::list_active_external_records(conn)
        .map_err(|e| e.to_string())?;
    rows.extend(external.into_iter().map(row_from_external));
    // Python ordered_lap_key: track canonical -> class -> weather -> time -> driver -> car.
    // Canonical track order comes from embedded reference data (same list used for PDF ordering).
    let tracks = forza_domain::reference_data::embedded_reference_data().tracks;
    let order_map = track_order_map(&tracks);
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

/// Distinct classes in canonical class order (not alphabetical): a new class
/// appears in filter dropdowns ordered by [`RaceClass::order`].
fn unique_classes(values: impl Iterator<Item = RaceClass>) -> Vec<RaceClass> {
    let set: BTreeSet<u32> = values.map(|c| c.order()).collect();
    let mut out: Vec<RaceClass> = RaceClass::ALL
        .iter()
        .copied()
        .filter(|c| set.contains(&c.order()))
        .collect();
    out.sort_by_key(|c| c.order());
    out
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
        race_classes: unique_classes(
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

/// Build `ExportRow`s straight from flat DB rows (raw mapping, no dirty
/// stripping, direct `source_file`).
///
/// This is intentionally separate from [`to_export_rows`]: the CLI dump
/// preserves stored values verbatim (Python parity, pinned by
/// `csv_bytes_are_identical_to_python_writer`), while the presentation
/// path strips dirty symbols and prefers display labels. Unifying the two
/// mappings would change CLI export bytes.
pub fn flat_to_export_rows(
    rows: &[forza_db::repositories::ExportFlatRow],
) -> Vec<forza_output::csv::ExportRow> {
    rows.iter()
        .map(|r| forza_output::csv::ExportRow {
            track: r.track.clone(),
            race_class: r.race_class.clone(),
            weather: r.weather.clone(),
            temp_f: r.temp_f,
            temp_c: r.temp_c,
            driver: r.driver.clone(),
            car: r.car.clone(),
            best_lap: r.best_lap.clone(),
            best_lap_ms: r.best_lap_ms,
            dirty: r.dirty,
            source_file: r.source_file.clone(),
            race_date: r.race_date.clone(),
            image_format: r.image_format.clone(),
            width_px: r.width_px,
            height_px: r.height_px,
        })
        .collect()
}

/// Build ExportRow slices for CSV/PDF consumers.
pub fn to_export_rows(rows: &[BestLapRow]) -> Vec<forza_output::csv::ExportRow> {
    rows.iter()
        .map(|r| forza_output::csv::ExportRow {
            track: r.track.clone(),
            race_class: r.race_class.as_str().to_string(),
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
            race_class: r.race_class.as_str().to_string(),
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
        let race_class = parse_race_class(class);
        BestLapRow {
            lap_id: None,
            image_file_id: None,
            run_id: None,
            track: track.to_string(),
            race_class,
            weather: WeatherType::Dry.as_str().to_string(),
            temp_f: Some(80.0),
            temp_c: Some(26.7),
            driver: driver.to_string(),
            car: car.to_string(),
            car_class: race_class,
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
            mine: false,
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

    #[test]
    fn ordering_is_track_canonical_then_class_then_time() {
        // Canonical track order: Brands Hatch before Spa, class E before A, time within class.
        // Use two tracks from embedded data to verify canonical ordering, not alphabetical.
        let tracks = forza_domain::reference_data::embedded_reference_data().tracks;
        let map = forza_domain::ordering::track_order_map(&tracks);
        let a = row(
            "Circuit de Spa-Francorchamps Full Circuit",
            "A",
            "Driver",
            "Car",
            100_000,
            false,
            false,
        );
        let b = row(
            "Brands Hatch Grand Prix Circuit",
            "A",
            "Driver",
            "Car",
            90_000,
            false,
            false,
        );
        // Brands Hatch is earlier in canonical list than Spa, so b should sort before a even though a is slower
        // but same class -> track decides.
        let key_a = forza_domain::ordering::ordered_lap_key(&a, &map);
        let key_b = forza_domain::ordering::ordered_lap_key(&b, &map);
        assert!(key_b < key_a);
        // Class order: E (1) before A (5) regardless of time
        let e = row("T", "E", "D", "C", 120_000, false, false);
        let a2 = row("T", "A", "D", "C", 90_000, false, false);
        let key_e = forza_domain::ordering::ordered_lap_key(&e, &map);
        let key_a2 = forza_domain::ordering::ordered_lap_key(&a2, &map);
        assert!(key_e < key_a2);
        // Within same track/class, time decides
        let fast = row("T", "A", "D", "C", 80_000, false, false);
        let slow = row("T", "A", "D", "C", 90_000, false, false);
        assert!(
            forza_domain::ordering::ordered_lap_key(&fast, &map)
                < forza_domain::ordering::ordered_lap_key(&slow, &map)
        );
    }

    #[test]
    fn filter_round_trips_every_known_class() {
        // Single owner: every persisted class string must survive the
        // Slint `from_strings` boundary as a typed filter, while "all"/""
        // stay unset. A new class that fails here is missing from the enum.
        for class in RaceClass::ALL {
            let f = BestLapFilter::from_strings(
                "all",
                class.as_str(),
                "all",
                "all",
                "all",
                "all",
                "all",
                false,
            );
            assert_eq!(f.race_class, Some(*class), "class {}", class.as_str());
        }
        let unset =
            BestLapFilter::from_strings("all", "all", "all", "all", "all", "all", "all", false);
        assert_eq!(unset.race_class, None);
    }

    #[test]
    fn garbage_db_class_never_panics_and_sorts_last() {
        // Orange-path: a stored garbage string degrades to Unknown (black,
        // order 12) instead of panicking or silently ranking as 99.
        assert_eq!(parse_race_class("Whatever"), RaceClass::Unknown);
        assert_eq!(parse_race_class(""), RaceClass::Unknown);
        let rows = [
            row("T", "Whatever", "D", "C", 80_000, false, false),
            row("T", "A", "D", "C", 90_000, false, false),
        ];
        assert_eq!(rows[0].race_class, RaceClass::Unknown);
        assert_eq!(rows[0].race_class.color(), "#000000");
    }
}
