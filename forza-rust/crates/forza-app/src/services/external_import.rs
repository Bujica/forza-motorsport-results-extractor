//! External records import (CSV + XLSX via calamine).

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

use calamine::{Data, Reader, open_workbook_auto};
use rusqlite::Connection;

use forza_db::repositories::external_records::{
    ExternalLapRecord, list_reference_cars, list_reference_tracks, replace_active_snapshot,
    seed_reference_cars,
};
use forza_domain::car_names::{canonicalize_car_name, car_canonical_map};

const REQUIRED_COLUMNS: &[&str] = &["Track", "Class", "Gamertag", "Vehicle", "Laptime"];
const MAX_XLSX_ROWS: usize = 100_000;
const DEFAULT_SHEET: &str = "MAIN LEADERBOARD";
const DEFAULT_ALIASES: &str = "data/external/track_aliases.json";

#[derive(Debug, Clone, PartialEq)]
pub struct ExternalImportResult {
    pub source_path: String,
    pub total_rows: usize,
    pub records: Vec<ExternalLapRecord>,
    pub unmapped_tracks: usize,
    pub invalid_laps: usize,
    pub canonicalized_cars: usize,
    pub new_cars: usize,
    pub ambiguous_cars: usize,
    pub new_car_names: Vec<String>,
    /// Full issue list for DB persistence (serialized as JSON).
    pub issues_json: String,
    pub rejected_rows: usize,
}

impl ExternalImportResult {
    pub fn message(&self) -> String {
        let mut parts = vec![
            format!(
                "External records imported: {} record(s) from {} row(s).",
                self.records.len(),
                self.total_rows
            ),
            format!("Canonicalized cars: {}.", self.canonicalized_cars),
            format!("New cars added: {}.", self.new_cars),
            format!("Unmapped tracks: {}.", self.unmapped_tracks),
            format!("Invalid laps: {}.", self.invalid_laps),
        ];
        if !self.new_car_names.is_empty() {
            let preview = self
                .new_car_names
                .iter()
                .take(8)
                .cloned()
                .collect::<Vec<_>>()
                .join(", ");
            let suffix = if self.new_car_names.len() > 8 {
                format!(", +{} more", self.new_car_names.len() - 8)
            } else {
                String::new()
            };
            parts.push(format!("New car list: {preview}{suffix}."));
        }
        if self.ambiguous_cars > 0 {
            parts.push(format!(
                "Ambiguous cars not added: {}.",
                self.ambiguous_cars
            ));
        }
        parts.join(" ")
    }
}

#[derive(Debug, Clone)]
struct Issue {
    kind: String,
    value: String,
    detail: String,
}

/// Import a spreadsheet file (CSV or XLSX) into normalized records (without DB).
pub fn import_spreadsheet(
    source_path: &Path,
    known_tracks: &[String],
    canonical_cars: &[String],
    aliases_file: Option<&Path>,
) -> Result<ExternalImportResult, String> {
    let raw_rows = if source_path
        .extension()
        .and_then(|e| e.to_str())
        .map(|e| e.eq_ignore_ascii_case("csv"))
        .unwrap_or(false)
    {
        read_csv_rows(source_path)?
    } else {
        read_xlsx_rows(source_path, DEFAULT_SHEET)?
    };
    let known_track_set: HashSet<String> = known_tracks
        .iter()
        .map(|t| t.trim().to_string())
        .filter(|t| !t.is_empty())
        .collect();
    let alias_path = aliases_file
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(DEFAULT_ALIASES));
    let (aliases, mut alias_issues) = load_aliases(&alias_path, &known_track_set);
    let (canonical_by_key, collisions) = car_canonical_map(
        &canonical_cars
            .iter()
            .map(|c| c.to_string())
            .collect::<Vec<_>>(),
    );
    // collisions is HashMap<String, Vec<String>>, need Option<&HashMap>
    let mut issues: Vec<Issue> = std::mem::take(&mut alias_issues);
    let mut seen_car_issues: HashSet<(String, String, String)> = HashSet::new();
    let mut best_by_group: HashMap<(String, String), ExternalLapRecord> = HashMap::new();

    for (row_number, row) in raw_rows.iter().enumerate() {
        let n = row_number + 1;
        let raw_track = row.get("Track").map(|s| s.trim()).unwrap_or("").to_string();
        let race_class = normalize_class(row.get("Class").map(|s| s.as_str()).unwrap_or(""));
        let driver = row
            .get("Gamertag")
            .map(|s| s.trim())
            .unwrap_or("")
            .to_string();
        let raw_car = row
            .get("Vehicle")
            .map(|s| s.trim())
            .unwrap_or("")
            .to_string();
        let raw_lap = row
            .get("Laptime")
            .map(|s| s.trim())
            .unwrap_or("")
            .to_string();
        let missing: Vec<&str> = [
            ("Track", raw_track.as_str()),
            ("Class", race_class.as_str()),
            ("Gamertag", driver.as_str()),
            ("Vehicle", raw_car.as_str()),
            ("Laptime", raw_lap.as_str()),
        ]
        .iter()
        .filter(|(_, v)| v.is_empty() || *v == "Unknown")
        .map(|(k, _)| *k)
        .collect();
        if !missing.is_empty() {
            issues.push(Issue {
                kind: "missing_required_fields".to_string(),
                value: format!("row {n}"),
                detail: missing.join(", "),
            });
            continue;
        }
        let track = if let Some(alias) = aliases.get(&raw_track) {
            alias.clone()
        } else if known_track_set.contains(&raw_track) {
            raw_track.clone()
        } else {
            issues.push(Issue {
                kind: "unmapped_track".to_string(),
                value: raw_track.clone(),
                detail: format!("row {n}"),
            });
            continue;
        };
        let (best_lap, best_lap_ms) = match normalize_lap(&raw_lap) {
            Ok((lap, ms)) => (lap, ms),
            Err(e) => {
                issues.push(Issue {
                    kind: "invalid_lap".to_string(),
                    value: raw_lap.clone(),
                    detail: format!("row {n}: {e}"),
                });
                continue;
            }
        };
        let car_result =
            canonicalize_car_name(Some(raw_car.as_str()), &canonical_by_key, Some(&collisions));
        let car = car_result.canonical.clone();
        let status = car_result.status.as_str();
        if status == "car_alias_canonicalized" {
            let key = (
                "car_alias_canonicalized".to_string(),
                raw_car.clone(),
                car.clone(),
            );
            if seen_car_issues.insert(key.clone()) {
                issues.push(Issue {
                    kind: key.0,
                    value: key.1,
                    detail: key.2,
                });
            }
        } else if status == "new_car" {
            let key = ("new_car".to_string(), raw_car.clone(), format!("row {n}"));
            if seen_car_issues.insert(key.clone()) {
                issues.push(Issue {
                    kind: key.0,
                    value: key.1,
                    detail: key.2,
                });
            }
        } else if status == "ambiguous_car" {
            let key = (
                "ambiguous_car".to_string(),
                raw_car.clone(),
                format!("row {n}: {}", car_result.key),
            );
            if seen_car_issues.insert(key.clone()) {
                issues.push(Issue {
                    kind: key.0,
                    value: key.1,
                    detail: key.2,
                });
            }
        }
        let rec = ExternalLapRecord {
            track: track.clone(),
            race_class: race_class.clone(),
            driver: driver.clone(),
            car: car.clone(),
            best_lap,
            best_lap_ms,
            source: "External".to_string(),
        };
        let key = (track.clone(), race_class.clone());
        match best_by_group.get(&key) {
            Some(current) if current.best_lap_ms <= rec.best_lap_ms => {}
            _ => {
                best_by_group.insert(key, rec);
            }
        }
    }
    let mut records: Vec<ExternalLapRecord> = best_by_group.into_values().collect();
    records.sort_by(|a, b| {
        a.track
            .to_lowercase()
            .cmp(&b.track.to_lowercase())
            .then_with(|| a.race_class.cmp(&b.race_class))
            .then_with(|| a.best_lap_ms.cmp(&b.best_lap_ms))
    });
    let unmapped = issues.iter().filter(|i| i.kind == "unmapped_track").count();
    let invalid = issues.iter().filter(|i| i.kind == "invalid_lap").count();
    let canonicalized = issues
        .iter()
        .filter(|i| i.kind == "car_alias_canonicalized")
        .count();
    let new_car_names: Vec<String> = {
        let mut set: HashSet<String> = HashSet::new();
        for i in &issues {
            if i.kind == "new_car" {
                set.insert(i.value.clone());
            }
        }
        let mut v: Vec<String> = set.into_iter().collect();
        v.sort();
        v
    };
    let new_cars = new_car_names.len();
    let ambiguous: usize = {
        let mut set: HashSet<String> = HashSet::new();
        for i in &issues {
            if i.kind == "ambiguous_car" {
                set.insert(i.value.clone());
            }
        }
        set.len()
    };
    let rejected = issues
        .iter()
        .filter(|i| {
            matches!(
                i.kind.as_str(),
                "missing_required_fields" | "unmapped_track" | "invalid_lap"
            )
        })
        .count();
    let issues_json = serde_json::to_string(
        &issues
            .iter()
            .map(|i| serde_json::json!({"kind": i.kind, "value": i.value, "detail": i.detail}))
            .collect::<Vec<_>>(),
    )
    .unwrap_or_else(|_| "[]".to_string());
    Ok(ExternalImportResult {
        source_path: source_path.to_string_lossy().to_string(),
        total_rows: raw_rows.len(),
        records,
        unmapped_tracks: unmapped,
        invalid_laps: invalid,
        canonicalized_cars: canonicalized,
        new_cars,
        ambiguous_cars: ambiguous,
        new_car_names,
        issues_json,
        rejected_rows: rejected,
    })
}

/// Import and atomically activate the snapshot in the DB.
pub fn import_to_db(conn: &Connection, source_path: &Path) -> Result<ExternalImportResult, String> {
    let _ = forza_db::migration::seed_reference_catalog(conn);
    let known_tracks = list_reference_tracks(conn).map_err(|e| e.to_string())?;
    let canonical_cars = list_reference_cars(conn).map_err(|e| e.to_string())?;
    let result = import_spreadsheet(source_path, &known_tracks, &canonical_cars, None)?;
    if !result.new_car_names.is_empty() {
        seed_reference_cars(conn, &result.new_car_names).map_err(|e| e.to_string())?;
    }
    let hash = file_sha256(source_path);
    replace_active_snapshot(
        conn,
        &result.records,
        &result.source_path,
        hash.as_deref(),
        result.total_rows as i64,
        result.rejected_rows as i64,
        Some(&result.issues_json),
    )
    .map_err(|e| e.to_string())?;
    Ok(result)
}

fn read_csv_rows(path: &Path) -> Result<Vec<HashMap<String, String>>, String> {
    let mut rdr = csv::ReaderBuilder::new()
        .has_headers(true)
        .from_path(path)
        .map_err(|e| format!("CSV open failed: {e}"))?;
    let raw_headers = rdr
        .headers()
        .map_err(|e| format!("CSV header failed: {e}"))?
        .clone();
    // Strip BOM (utf-8-sig) from first header like Python's encoding="utf-8-sig".
    let headers: Vec<String> = raw_headers
        .iter()
        .map(|h| h.trim_start_matches('\u{feff}').trim().to_string())
        .collect();
    let missing: Vec<String> = REQUIRED_COLUMNS
        .iter()
        .filter(|c| !headers.iter().any(|h| h == **c))
        .map(|c| (*c).to_string())
        .collect();
    if !missing.is_empty() {
        return Err(format!("CSV missing required columns: {missing:?}"));
    }
    let mut rows = Vec::new();
    for rec in rdr.records() {
        let rec = rec.map_err(|e| format!("CSV record failed: {e}"))?;
        let mut map = HashMap::new();
        for (h, v) in headers.iter().zip(rec.iter()) {
            map.insert(h.to_string(), v.to_string());
        }
        rows.push(map);
    }
    Ok(rows)
}

fn read_xlsx_rows(path: &Path, sheet_name: &str) -> Result<Vec<HashMap<String, String>>, String> {
    if !path.exists() {
        return Err(format!("File not found: {}", path.display()));
    }
    let mut workbook = open_workbook_auto(path).map_err(|e| format!("XLSX open failed: {e}"))?;
    let range = match workbook.worksheet_range(sheet_name) {
        Ok(r) => r,
        Err(_) => {
            // Fallback: case-insensitive sheet lookup (handles "Main Leaderboard" vs "MAIN LEADERBOARD")
            let names = workbook.sheet_names().to_owned();
            let found = names
                .iter()
                .find(|n| n.eq_ignore_ascii_case(sheet_name))
                .cloned();
            if let Some(actual) = found {
                workbook
                    .worksheet_range(&actual)
                    .map_err(|e| format!("Worksheet '{actual}' not found: {e}"))?
            } else {
                return Err(format!(
                    "Worksheet '{sheet_name}' not found. Available: {:?}",
                    workbook.sheet_names()
                ));
            }
        }
    };
    if range.is_empty() {
        return Err(format!("Worksheet '{sheet_name}' is empty"));
    }
    let rows: Vec<Vec<String>> = range
        .rows()
        .map(|row| {
            row.iter()
                .map(|c| match c {
                    Data::Empty => String::new(),
                    Data::String(s) => s.clone(),
                    Data::Float(f) => {
                        if f.fract() == 0.0 {
                            format!("{}", *f as i64)
                        } else {
                            format!("{f}")
                        }
                    }
                    Data::Int(i) => format!("{i}"),
                    Data::Bool(b) => format!("{b}"),
                    Data::Error(e) => format!("{e:?}"),
                    Data::DateTime(d) => format!("{d}"),
                    Data::DateTimeIso(s) => s.clone(),
                    Data::DurationIso(s) => s.clone(),
                })
                .collect()
        })
        .collect();
    if rows.len() > MAX_XLSX_ROWS {
        return Err(format!(
            "XLSX row limit exceeded: {} > {}",
            rows.len(),
            MAX_XLSX_ROWS
        ));
    }
    let mut headers: Option<Vec<String>> = None;
    let mut result = Vec::new();
    for values in &rows {
        if headers.is_none() {
            let set: HashSet<String> = values
                .iter()
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .collect();
            if REQUIRED_COLUMNS.iter().all(|c| set.contains(*c)) {
                headers = Some(values.iter().map(|s| s.trim().to_string()).collect());
            }
            continue;
        }
        let Some(h) = headers.as_ref() else {
            continue;
        };
        let mut mapped = HashMap::new();
        for (i, v) in values.iter().enumerate() {
            if i < h.len() {
                mapped.insert(h[i].clone(), v.clone());
            }
        }
        if REQUIRED_COLUMNS.iter().any(|k| {
            mapped
                .get(*k)
                .map(|v| !v.trim().is_empty())
                .unwrap_or(false)
        }) {
            result.push(mapped);
        }
    }
    if headers.is_none() {
        return Err(format!(
            "Worksheet '{sheet_name}' is missing required headers: {:?}",
            REQUIRED_COLUMNS
        ));
    }
    Ok(result)
}

fn load_aliases(
    path: &Path,
    known_tracks: &HashSet<String>,
) -> (HashMap<String, String>, Vec<Issue>) {
    let mut issues = Vec::new();
    if !path.exists() {
        return (HashMap::new(), issues);
    }
    let text = match std::fs::read_to_string(path) {
        Ok(t) => t,
        Err(_) => return (HashMap::new(), issues),
    };
    let payload: serde_json::Value = match serde_json::from_str(&text) {
        Ok(v) => v,
        Err(_) => return (HashMap::new(), issues),
    };
    let Some(obj) = payload.as_object() else {
        return (HashMap::new(), issues);
    };
    let mut aliases = HashMap::new();
    for (k, v) in obj {
        let source = k.trim().to_string();
        let target = v.as_str().unwrap_or("").trim().to_string();
        if source.is_empty() || target.is_empty() {
            issues.push(Issue {
                kind: "invalid_alias".to_string(),
                value: if source.is_empty() {
                    "<blank>".to_string()
                } else {
                    source
                },
                detail: "blank source or target".to_string(),
            });
            continue;
        }
        if !known_tracks.is_empty() && !known_tracks.contains(&target) {
            issues.push(Issue {
                kind: "invalid_alias".to_string(),
                value: source.clone(),
                detail: target.clone(),
            });
            continue;
        }
        aliases.insert(source, target);
    }
    (aliases, issues)
}

fn normalize_class(value: &str) -> String {
    let v = value.trim().to_uppercase();
    if v.is_empty() {
        return "Unknown".to_string();
    }
    if v.starts_with("TCR") {
        return "TCR".to_string();
    }
    v.chars()
        .next()
        .map(|c| c.to_string())
        .unwrap_or_else(|| "Unknown".to_string())
}

fn normalize_lap(raw: &str) -> Result<(String, i64), String> {
    let cleaned: String = raw
        .chars()
        .filter(|c| c.is_ascii_digit() || *c == ':' || *c == '.')
        .collect();
    if !cleaned.contains(':') {
        return Err(format!("No colon in lap time: {raw:?}"));
    }
    let parts: Vec<&str> = cleaned.splitn(2, ':').collect();
    let mins: i64 = parts[0]
        .parse()
        .map_err(|e| format!("minutes parse: {e}"))?;
    let secs: f64 = parts[1]
        .parse()
        .map_err(|e| format!("seconds parse: {e}"))?;
    let lap = format!("{mins:02}:{secs:06.3}");
    let ms = (mins * 60 * 1000) + (secs * 1000.0).round() as i64;
    Ok((lap, ms))
}

fn file_sha256(path: &Path) -> Option<String> {
    let data = std::fs::read(path).ok()?;
    use sha2::{Digest, Sha256};
    let mut hasher = Sha256::new();
    hasher.update(&data);
    let result = hasher.finalize();
    Some(format!("{result:x}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalize_class_variants() {
        assert_eq!(normalize_class(" tcr "), "TCR");
        assert_eq!(normalize_class("A"), "A");
        assert_eq!(normalize_class(""), "Unknown");
        assert_eq!(normalize_class("TCR something"), "TCR");
    }

    #[test]
    fn normalize_lap_ok() {
        let (lap, ms) = normalize_lap("1:31.900").unwrap();
        assert_eq!(lap, "01:31.900");
        assert_eq!(ms, 91_900);
    }

    #[test]
    fn import_csv_end_to_end() {
        let dir = tempfile::tempdir().unwrap();
        let db_path = dir.path().join("test.db");
        forza_db::upgrade(&db_path).unwrap();
        let conn = forza_db::open_connection(&db_path).unwrap();
        let csv_path = dir.path().join("test.csv");
        std::fs::write(
            &csv_path,
            "Track,Class,Gamertag,Vehicle,Laptime\n\"Daytona International Speedway Sports Car Circuit\",A,TestDriver,\"Audi R8 LMS\",1:30.000\n",
        )
        .unwrap();
        let res = import_to_db(&conn, &csv_path).unwrap();
        assert_eq!(res.records.len(), 1);
        assert_eq!(res.total_rows, 1);
        let active =
            forza_db::repositories::external_records::list_active_external_records(&conn).unwrap();
        assert_eq!(active.len(), 1);
        assert_eq!(
            active[0].track,
            "Daytona International Speedway Sports Car Circuit"
        );
    }
}
