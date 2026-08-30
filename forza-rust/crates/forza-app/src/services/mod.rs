pub mod best_laps;
pub mod external_import;
pub mod extraction_replay;
pub mod extraction_runner;
pub mod image_debug;
pub mod image_detail;
pub mod image_inventory;
pub mod rebuild;
pub mod review_queue;
pub mod run_control;
pub mod settings;

use rusqlite::Connection;

pub use extraction_replay::{ReplayOutcome, replay_recorded_response};
pub use extraction_runner::{RunEvent, RunParams, spawn_extraction};
pub use image_debug::{
    ImageDebugFilter, list_debug_cases, load_debug_detail, load_debug_detail_by_result,
};
pub use image_detail::{ImageDetailData, load_image_detail};
pub use image_inventory::ImageInventoryOptions;
pub use rebuild::{RebuildOutcome, rebuild};
pub use review_queue::{
    ReviewCaseEntry, ReviewQueueFilter, decide_case, ignore_case, list_review_cases, reopen_case,
};
pub use run_control::RunControl;
pub use settings::{SettingRow, SettingsSnapshot, settings_snapshot};

/// Best-lap row for GUI/output consumers (thin projection of ExportFlatRow).
#[derive(Debug, Clone, PartialEq)]
pub struct BestLapEntry {
    pub track: String,
    pub race_class: String,
    pub weather: String,
    pub temp_c: Option<f64>,
    pub driver: String,
    pub car: String,
    pub best_lap: Option<String>,
    pub best_lap_ms: Option<i64>,
    pub dirty: bool,
    pub mine: bool,
}

/// List clean best laps through the read facade.
pub fn list_clean_flat_entries(
    conn: &Connection,
    gamertag_lower: &str,
) -> Result<Vec<BestLapEntry>, String> {
    let rows = forza_db::repositories::laps::list_clean_flat(conn, gamertag_lower)
        .map_err(|e| e.to_string())?;
    Ok(rows
        .into_iter()
        .map(|r| BestLapEntry {
            track: r.track,
            race_class: r.race_class,
            weather: r.weather.unwrap_or_else(|| "unknown".into()),
            temp_c: r.temp_c,
            driver: r.driver,
            car: r.car,
            best_lap: r.best_lap,
            best_lap_ms: r.best_lap_ms,
            dirty: r.dirty,
            mine: r.mine,
        })
        .collect())
}

/// Doctor summary shaped for the diagnostics screen.
#[derive(Debug, Clone, PartialEq)]
pub struct DoctorSummary {
    pub ok: bool,
    pub schema_status: String,
    pub user_version: i64,
    pub checks: Vec<(String, bool, String)>,
}

impl DoctorSummary {
    pub fn from_report(report: forza_db::doctor::DoctorReport) -> Self {
        Self {
            ok: report.ok,
            schema_status: report.schema_status,
            user_version: report.user_version,
            checks: report
                .checks
                .into_iter()
                .map(|c| (c.key.to_string(), c.ok, c.detail))
                .collect(),
        }
    }
}

/// Run the DB doctor battery for GUI consumers.
pub fn run_doctor(database_file: &std::path::Path) -> Result<DoctorSummary, String> {
    forza_db::doctor::doctor_on_path(database_file)
        .map(DoctorSummary::from_report)
        .map_err(|e| e.to_string())
}

pub use image_inventory::{ImageInventoryEntry, ImageInventoryFilter, ImageInventoryService};
