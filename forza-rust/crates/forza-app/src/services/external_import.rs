//! External records import (CSV + XLSX via calamine in Fase D3).

// Placeholder for D1 — full calamine import lands in D3.
// This module stays thin; business rules live here, persistence via forza-db.

use std::path::Path;

#[derive(Debug, Clone, PartialEq)]
pub struct ExternalImportResult {
    pub source_path: String,
    pub total_rows: usize,
    pub records: Vec<forza_db::repositories::external_records::ExternalLapRecord>,
    pub unmapped_tracks: usize,
    pub invalid_laps: usize,
    pub canonicalized_cars: usize,
    pub new_cars: usize,
    pub ambiguous_cars: usize,
    pub new_car_names: Vec<String>,
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

/// Stub importer — reads CSV only for D1 smoke; XLSX via calamine in D3.
pub fn import_external_records_stub(_path: &Path) -> Result<ExternalImportResult, String> {
    Err("XLSX/CSV import lands in D3 (calamine)".to_string())
}
