//! Output artifacts: CSV and PDF best-laps reports (migration §4.7).

pub mod csv;
pub mod pdf;

pub use csv::{ExportError, export_csv};
pub use pdf::{PdfDocumentPlan, PdfRow, PdfSection, PdfTable, build_pdf_plan};
