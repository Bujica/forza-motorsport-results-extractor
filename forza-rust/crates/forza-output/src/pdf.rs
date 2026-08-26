//! PDF content plan: the deterministic "list" that the renderer draws.
//! Mirrors `forza/output/pdf.py` — `_build_data_map`, canonical track order,
//! class ordering, per-bucket time sort with player-first tie-break.

use forza_domain::ordering::{class_order_key, track_order_key, track_order_map};
use std::path::Path;

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

#[derive(Debug, thiserror::Error)]
pub enum PdfRenderError {
    #[error("I/O error: {0}")]
    Io(String),
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

/// Render the deterministic plan as a dependency-free, readable PDF.
///
/// This is intentionally kept below the planning layer: ordering and content
/// remain testable without parsing PDF bytes, while the CLI gets a real PDF
/// artifact before the full ReportLab-style layout is ported.
pub fn render_pdf(plan: &PdfDocumentPlan, path: &Path) -> Result<(), PdfRenderError> {
    let mut pages: Vec<String> = Vec::new();
    let mut page = Vec::new();
    page.push("Forza Motorsport - Best Laps".to_string());
    page.push(format!(
        "{} | {} track(s), {} class(es), {} lap(s)",
        plan.gamertag, plan.stats.tracks, plan.stats.classes, plan.stats.laps
    ));
    page.push(String::new());
    page.push("Track index".to_string());
    for (index, section) in plan.sections.iter().enumerate() {
        page.push(format!("{}. {}", index + 1, section.track));
    }
    pages.push(page.join("\n"));

    for section in &plan.sections {
        let mut lines = vec![format!("Track: {}", section.track)];
        for table in &section.tables {
            lines.push(format!("Class {}", table.class));
            lines.push("Driver | Car | Best lap | Flags".to_string());
            for row in &table.rows {
                let mut flags = String::new();
                if row.mine {
                    flags.push_str("mine ");
                }
                if row.dirty {
                    flags.push_str("dirty ");
                }
                if row.external {
                    flags.push_str("external ");
                }
                lines.push(format!(
                    "{} | {} | {} | {}",
                    row.driver,
                    row.car,
                    row.time_str,
                    flags.trim()
                ));
            }
            lines.push(String::new());
        }
        for chunk in lines.chunks(42) {
            pages.push(chunk.join("\n"));
        }
    }

    let mut objects: Vec<Vec<u8>> = vec![Vec::new()];
    let catalog_id = add_object(&mut objects, b"<< /Type /Catalog /Pages 2 0 R >>");
    let pages_id = add_object(&mut objects, b"PLACEHOLDER");
    let font_id = add_object(
        &mut objects,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    );
    let mut page_ids = Vec::new();
    for text in pages {
        let stream = pdf_stream(&text);
        let content_id = add_object(&mut objects, stream.as_bytes());
        let page_body = format!(
            "<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
        );
        page_ids.push(add_object(&mut objects, page_body.as_bytes()));
    }
    let kids = page_ids
        .iter()
        .map(|id| format!("{id} 0 R"))
        .collect::<Vec<_>>()
        .join(" ");
    objects[pages_id - 1] = format!(
        "<< /Type /Pages /Kids [{kids}] /Count {} >>",
        page_ids.len()
    )
    .into_bytes();
    // The catalog was allocated before the pages object and already points at
    // object 2, which is the stable pages id by construction.
    let _ = catalog_id;

    let mut pdf = b"%PDF-1.4\n%\xE2\xE3\xCF\xD3\n".to_vec();
    let mut offsets = vec![0usize];
    for (index, object) in objects.iter().enumerate().skip(1) {
        offsets.push(pdf.len());
        pdf.extend_from_slice(format!("{index} 0 obj\n").as_bytes());
        pdf.extend_from_slice(object);
        pdf.extend_from_slice(b"\nendobj\n");
    }
    let xref = pdf.len();
    pdf.extend_from_slice(format!("xref\n0 {}\n", objects.len()).as_bytes());
    pdf.extend_from_slice(b"0000000000 65535 f \n");
    for offset in offsets.iter().skip(1) {
        pdf.extend_from_slice(format!("{offset:010} 00000 n \n").as_bytes());
    }
    pdf.extend_from_slice(
        format!(
            "trailer\n<< /Size {} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n",
            objects.len()
        )
        .as_bytes(),
    );
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| PdfRenderError::Io(e.to_string()))?;
    }
    std::fs::write(path, pdf).map_err(|e| PdfRenderError::Io(e.to_string()))?;
    Ok(())
}

fn add_object(objects: &mut Vec<Vec<u8>>, body: &[u8]) -> usize {
    objects.push(body.to_vec());
    objects.len() - 1
}

fn pdf_stream(text: &str) -> String {
    let mut stream = String::from("<< /Length ");
    let commands = text
        .lines()
        .enumerate()
        .map(|(index, line)| {
            let y = 806 - index as i32 * 18;
            format!(
                "BT /F1 {} Tf 36 {} Td ({}) Tj ET",
                if index == 0 { 16 } else { 9 },
                y,
                pdf_escape(line)
            )
        })
        .collect::<Vec<_>>()
        .join("\n");
    stream.push_str(&commands.len().to_string());
    stream.push_str(" >>\nstream\n");
    stream.push_str(&commands);
    stream.push_str("\nendstream");
    stream
}

fn pdf_escape(value: &str) -> String {
    value
        .chars()
        .map(|c| if c.is_ascii() { c } else { '?' })
        .collect::<String>()
        .replace('\\', "\\\\")
        .replace('(', "\\(")
        .replace(')', "\\)")
}
