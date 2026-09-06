//! Output artifacts: CSV and PDF best-laps reports (migration §4.7).

pub mod csv;
pub mod pdf;

pub use csv::{ExportError, export_csv};
pub use pdf::{
    PdfDocumentPlan, PdfExternalRecord, PdfRenderError, PdfRenderOptions, PdfRow, PdfSection,
    PdfTable, build_pdf_plan, build_pdf_plan_ext, render_pdf,
};

/// Python-style float formatting shared by CSV, PDF, and best-laps export:
/// integral values below 1e15 render with one decimal (`45.0`), everything
/// else with Rust display (matches the Python writers byte-for-byte on the
/// golden fixtures).
pub fn fmt_float(v: f64) -> String {
    if v == v.trunc() && v.abs() < 1e15 {
        format!("{v:.1}")
    } else {
        format!("{v}")
    }
}
