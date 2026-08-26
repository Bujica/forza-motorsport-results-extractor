//! CSV export byte-compatible with `forza/output/csv.py`
//! (UTF-8 BOM, CRLF line endings, QUOTE_MINIMAL, None → empty).

use std::io::Write;
use std::path::Path;

#[derive(Debug, thiserror::Error)]
pub enum ExportError {
    #[error("I/O error: {0}")]
    Io(String),
}

/// One clean-flat export row (mirrors the Python `ExportLap` read model).
#[derive(Debug, Clone, Default, PartialEq)]
pub struct ExportRow {
    pub track: String,
    pub race_class: String,
    pub weather: Option<String>,
    pub temp_f: Option<f64>,
    pub temp_c: Option<f64>,
    pub driver: String,
    pub car: String,
    pub best_lap: Option<String>,
    pub best_lap_ms: Option<i64>,
    pub dirty: bool,
    pub source_file: Option<String>,
    /// ISO date string (already formatted) or absent.
    pub race_date: Option<String>,
    pub image_format: Option<String>,
    pub width_px: Option<i64>,
    pub height_px: Option<i64>,
}

const CSV_FIELDS: &[&str] = &[
    "track",
    "race_class",
    "weather",
    "temp_f",
    "temp_c",
    "driver",
    "car",
    "best_lap",
    "best_lap_ms",
    "dirty",
    "source_file",
    "race_date",
    "image_format",
    "width_px",
    "height_px",
];

fn field_value(row: &ExportRow, field: &str) -> String {
    match field {
        "track" => row.track.clone(),
        "race_class" => row.race_class.clone(),
        "weather" => row.weather.clone().unwrap_or_default(),
        "temp_f" => row.temp_f.map(fmt_float).unwrap_or_default(),
        "temp_c" => row.temp_c.map(fmt_float).unwrap_or_default(),
        "driver" => row.driver.clone(),
        "car" => row.car.clone(),
        "best_lap" => row.best_lap.clone().unwrap_or_default(),
        "best_lap_ms" => row.best_lap_ms.map(|v| v.to_string()).unwrap_or_default(),
        // Python writes booleans via str(): capitalised.
        "dirty" => {
            if row.dirty {
                "True".into()
            } else {
                "False".into()
            }
        }
        "source_file" => row.source_file.clone().unwrap_or_default(),
        "race_date" => row.race_date.clone().unwrap_or_default(),
        "image_format" => row.image_format.clone().unwrap_or_default(),
        "width_px" => row.width_px.map(|v| v.to_string()).unwrap_or_default(),
        "height_px" => row.height_px.map(|v| v.to_string()).unwrap_or_default(),
        other => unreachable!("unknown csv field {other}"),
    }
}

/// Python str(float): 80.0 → "80.0", 26.7 → "26.7".
fn fmt_float(v: f64) -> String {
    if v == v.trunc() && v.abs() < 1e15 {
        format!("{v:.1}")
    } else {
        format!("{v}")
    }
}

fn quote_minimal(field: &str, out: &mut String) {
    let needs =
        field.contains(',') || field.contains('"') || field.contains('\n') || field.contains('\r');
    if needs {
        out.push('"');
        for ch in field.chars() {
            if ch == '"' {
                out.push('"');
            }
            out.push(ch);
        }
        out.push('"');
    } else {
        out.push_str(field);
    }
}

/// Write the flat CSV; returns the number of rows written.
pub fn export_csv(rows: &[ExportRow], out_path: &Path) -> Result<usize, ExportError> {
    if let Some(parent) = out_path.parent()
        && !parent.as_os_str().is_empty()
        && !parent.exists()
    {
        std::fs::create_dir_all(parent).map_err(|e| ExportError::Io(e.to_string()))?;
    }

    let mut bytes: Vec<u8> = Vec::new();
    // encoding="utf-8-sig"
    bytes.extend_from_slice(&[0xEF, 0xBB, 0xBF]);

    let mut header_line = String::new();
    for (i, field) in CSV_FIELDS.iter().enumerate() {
        if i > 0 {
            header_line.push(',');
        }
        header_line.push_str(field);
    }
    header_line.push_str("\r\n");
    bytes.extend_from_slice(header_line.as_bytes());

    for row in rows {
        let mut line = String::new();
        for (i, field) in CSV_FIELDS.iter().enumerate() {
            if i > 0 {
                line.push(',');
            }
            quote_minimal(&field_value(row, field), &mut line);
        }
        line.push_str("\r\n");
        bytes.extend_from_slice(line.as_bytes());
    }

    let mut file = std::fs::File::create(out_path).map_err(|e| ExportError::Io(e.to_string()))?;
    file.write_all(&bytes)
        .map_err(|e| ExportError::Io(e.to_string()))?;
    Ok(rows.len())
}
