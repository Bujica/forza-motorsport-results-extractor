//! PDF content plan: the deterministic "list" that the renderer draws.
//! Mirrors `forza/output/pdf.py` — `_build_data_map`, canonical track order,
//! class ordering, per-bucket time sort with player-first tie-break.

use forza_domain::ordering::{class_order_key, track_order_key, track_order_map};

use crate::csv::ExportRow;

/// One rendered row inside a class table.
#[derive(Debug, Clone, PartialEq)]
pub struct PdfRow {
    pub driver: String,
    pub car: String,
    pub time_str: String,
    pub dirty: bool,
    pub mine: bool,
    /// Integer milliseconds — the domain ordering contract.
    pub time_ms: i64,
    pub temp_c: Option<f64>,
    /// External/community records have no source file.
    pub external: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PdfTable {
    pub class: String,
    pub color_hex: String,
    pub rows: Vec<PdfRow>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PdfSection {
    pub track: String,
    pub tables: Vec<PdfTable>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PdfDocumentPlan {
    pub gamertag: String,
    pub stats: PdfStats,
    pub sections: Vec<PdfSection>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PdfStats {
    pub tracks: usize,
    pub classes: usize,
    pub laps: usize,
}

fn class_colors(class: &str) -> &'static str {
    match class {
        "E" => "#C7368E",
        "D" => "#127F85",
        "C" => "#BB7A00",
        "B" => "#C54E00",
        "A" => "#992800",
        "TCR" => "#1E90FF",
        "S" => "#613BBF",
        "R" => "#105DAB",
        "P" => "#0C8540",
        "X" => "#006000",
        "Mixed" => "#555555",
        _ => "#000000",
    }
}

/// Build the deterministic document plan (the report's list content).
///
/// `track_order` is the canonical track list defining section order.
/// External/community records are merged into the same buckets, marked
/// external, and never contribute source files.
pub fn build_pdf_plan(
    rows: &[ExportRow],
    gamertag: &str,
    track_order: &[String],
) -> PdfDocumentPlan {
    let gamertag_lower = gamertag.to_lowercase();

    // track → class → rows
    let mut data_map: std::collections::BTreeMap<
        String,
        std::collections::BTreeMap<String, Vec<PdfRow>>,
    > = Default::default();

    for row in rows {
        let track = if row.track.is_empty() {
            "Unknown".to_string()
        } else {
            row.track.clone()
        };
        data_map
            .entry(track)
            .or_default()
            .entry(row.race_class.clone())
            .or_default()
            .push(PdfRow {
                driver: row.driver.clone(),
                car: row.car.clone(),
                time_str: row.best_lap.clone().unwrap_or_default(),
                dirty: row.dirty,
                mine: row.driver.to_lowercase() == gamertag_lower,
                time_ms: row.best_lap_ms.unwrap_or(i64::MAX),
                temp_c: row.temp_c,
                external: false,
            });
    }

    // Sort every bucket: fastest first, player before others on tie
    // (Python key: (time_sec, not mine)).
    for classes in data_map.values_mut() {
        for bucket in classes.values_mut() {
            bucket.sort_by(|a, b| a.time_ms.cmp(&b.time_ms).then_with(|| b.mine.cmp(&a.mine)));
        }
    }

    let order_index = track_order_map(track_order);
    let mut sorted_tracks: Vec<&String> = data_map.keys().collect();
    sorted_tracks.sort_by_key(|t| track_order_key(t, &order_index));

    let mut sections = Vec::new();
    for track in sorted_tracks {
        let classes = &data_map[track];
        let mut sorted_classes: Vec<&String> = classes.keys().collect();
        sorted_classes.sort_by_key(|c| class_order_key(c));
        let mut tables = Vec::new();
        for cls in sorted_classes {
            let rows = &classes[cls];
            tables.push(PdfTable {
                class: cls.clone(),
                color_hex: class_colors(cls).to_string(),
                rows: rows.clone(),
            });
        }
        sections.push(PdfSection {
            track: track.clone(),
            tables,
        });
    }

    let stats = PdfStats {
        tracks: sections.len(),
        classes: sections.iter().map(|s| s.tables.len()).sum(),
        laps: sections
            .iter()
            .flat_map(|s| s.tables.iter())
            .map(|t| t.rows.len())
            .sum(),
    };

    PdfDocumentPlan {
        gamertag: gamertag.to_string(),
        stats,
        sections,
    }
}
