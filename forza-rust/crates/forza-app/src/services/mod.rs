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

#[derive(Debug, Clone, PartialEq)]
pub struct DoctorCheckSummary {
    pub key: String,
    pub ok: bool,
    pub count: i64,
    pub detail: String,
    pub severity: String,
    pub result: String,
}

/// Doctor summary shaped for the diagnostics screen.
#[derive(Debug, Clone, PartialEq)]
pub struct DoctorSummary {
    pub ok: bool,
    pub schema_status: String,
    pub user_version: i64,
    pub overall: String,
    pub summary_text: String,
    pub checks: Vec<DoctorCheckSummary>,
}

impl DoctorSummary {
    pub fn from_report(report: forza_db::doctor::DoctorReport) -> Self {
        let checks: Vec<DoctorCheckSummary> = report
            .checks
            .iter()
            .map(|c| {
                let result = if c.ok {
                    "PASS".to_string()
                } else if c.severity == forza_db::doctor::DoctorSeverity::Warning {
                    "WARN".to_string()
                } else {
                    "FAIL".to_string()
                };
                DoctorCheckSummary {
                    key: c.key.to_string(),
                    ok: c.ok,
                    count: c.count,
                    detail: c.detail.clone(),
                    severity: c.severity.as_str().to_string(),
                    result,
                }
            })
            .collect();
        let errors = checks.iter().filter(|c| c.result == "FAIL").count();
        let warnings = checks.iter().filter(|c| c.result == "WARN").count();
        let passing = checks.iter().filter(|c| c.result == "PASS").count();
        let overall = if !report.ok || errors > 0 {
            "FAIL"
        } else if warnings > 0 {
            "WARN"
        } else {
            "PASS"
        }
        .to_string();
        let summary_text = format!(
            "{} · schema={} · {} error, {} warning, {} passed",
            report.schema_status, report.schema_status, errors, warnings, passing
        );
        // Keep schema_status as is; UI builds richer summary.
        let _ = summary_text;
        let display_summary = format!(
            "schema={} (v{}) · {} error, {} warning, {} passed",
            report.schema_status, report.user_version, errors, warnings, passing
        );
        Self {
            ok: report.ok,
            schema_status: report.schema_status,
            user_version: report.user_version,
            overall,
            summary_text: display_summary,
            checks,
        }
    }
}

/// Run the DB doctor battery for GUI consumers.
pub fn run_doctor(database_file: &std::path::Path) -> Result<DoctorSummary, String> {
    forza_db::doctor::doctor_on_path(database_file)
        .map(DoctorSummary::from_report)
        .map_err(|e| e.to_string())
}

pub fn run_full_doctor_on_path(database_file: &std::path::Path) -> Result<DoctorSummary, String> {
    let status = forza_db::migration::schema_status(database_file).map_err(|e| e.to_string())?;
    let status_label = match status {
        forza_db::migration::SchemaStatus::Empty => "empty".to_string(),
        forza_db::migration::SchemaStatus::Current => "current".to_string(),
        forza_db::migration::SchemaStatus::Incompatible { found } => {
            if found == 0 {
                "empty".to_string()
            } else {
                format!("incompatible({found})")
            }
        }
    };
    // Open connection if possible; for empty we still produce a report.
    match status {
        forza_db::migration::SchemaStatus::Empty => {
            let report = forza_db::doctor::DoctorReport {
                ok: false,
                schema_status: "empty".to_string(),
                user_version: 0,
                checks: vec![forza_db::doctor::DoctorCheck {
                    key: "database_exists",
                    ok: false,
                    count: 1,
                    detail: "no database file or empty database".to_string(),
                    severity: forza_db::doctor::DoctorSeverity::Error,
                }],
            };
            Ok(DoctorSummary::from_report(report))
        }
        _ => {
            let conn = forza_db::open_connection(database_file).map_err(|e| e.to_string())?;
            // Determine precise schema_status label via doctor helper
            let precise_status = {
                // Use doctor's internal label if possible: rely on schema_state_label via full report
                // Fallback to status_label
                status_label
            };
            forza_db::doctor::run_full_doctor(&conn, precise_status)
                .map(DoctorSummary::from_report)
                .map_err(|e| e.to_string())
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct FastDbReport {
    pub schema_state: String,
    pub ok: bool,
    pub errors: i64,
    pub warnings: i64,
}

pub fn fast_db_report(database_file: &std::path::Path) -> FastDbReport {
    let schema_state = forza_db::migration::schema_status(database_file)
        .map(|s| match s {
            forza_db::migration::SchemaStatus::Empty => "empty".to_string(),
            forza_db::migration::SchemaStatus::Current => "current".to_string(),
            forza_db::migration::SchemaStatus::Incompatible { found } => {
                format!("incompatible({found})")
            }
        })
        .unwrap_or_else(|_| "error".to_string());
    if schema_state != "current" {
        return FastDbReport {
            schema_state,
            ok: false,
            errors: 1,
            warnings: 0,
        };
    }
    let conn = match forza_db::open_connection(database_file) {
        Ok(c) => c,
        Err(_) => {
            return FastDbReport {
                schema_state,
                ok: false,
                errors: 1,
                warnings: 0,
            };
        }
    };
    let quick: String = conn
        .query_row("PRAGMA quick_check", [], |r| r.get(0))
        .unwrap_or_else(|_| "error".to_string());
    let mut errors: i64 = 0;
    if quick.to_lowercase() != "ok" {
        errors += 1;
    }
    // Count foreign key violations via dedicated query
    let fk_count: i64 = {
        let stmt = conn.prepare("PRAGMA foreign_key_check").ok();
        if let Some(mut s) = stmt {
            s.query_map([], |row| row.get::<_, String>(0))
                .map(|iter| iter.count() as i64)
                .unwrap_or(0)
        } else {
            0
        }
    };
    errors += fk_count;
    let pending: i64 = conn.query_row(
        "SELECT COUNT(*) FROM image_files si JOIN lap_records lr ON lr.image_file_id = si.id WHERE si.best_lap_status = 'pending' AND si.file_status = 'available' AND lr.dirty = 0 AND COALESCE(lr.best_lap_ms, 0) > 0",
        [],
        |r| r.get(0),
    ).unwrap_or(0);
    errors += pending;
    FastDbReport {
        schema_state,
        ok: errors == 0,
        errors,
        warnings: 0,
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct OverviewSnapshot {
    pub lm_endpoint: String,
    pub lm_model: String,
    pub lm_loaded_instance: String,
    pub lm_configured_load: String,
    pub lm_configured_request: String,
    pub lm_configured_image: String,
    pub lm_runtime_policy: String,
    pub lm_loaded_runtime: String,
    pub lm_capabilities: String,
    pub lm_model_info: String,
    pub lm_warnings: String,
    pub lm_level: String,
    pub lm_message: String,
    pub lm_ok: bool,
    pub db_ok: bool,
    pub db_errors: i64,
    pub db_warnings: i64,
    pub schema_state: String,
    pub database_file: String,
    pub images: i64,
    pub available_images: i64,
    pub review_open: i64,
}

fn api_base(url: &str) -> String {
    let clean = url.trim_end_matches('/');
    if let Some(idx) = clean.find("/api/v1/") {
        return format!("{}/api/v1", &clean[..idx]);
    }
    if clean.ends_with("/api/v1") {
        return clean.to_string();
    }
    if let Some(idx) = clean.find("/v1/") {
        return format!("{}/api/v1", &clean[..idx]);
    }
    clean.to_string()
}

fn lm_ping_blocking(url: &str) -> (bool, String, String) {
    let endpoint = format!("{}/models", api_base(url));
    let client = match reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(1))
        .build()
    {
        Ok(c) => c,
        Err(e) => {
            return (
                false,
                "error".to_string(),
                format!("client build failed: {e}"),
            );
        }
    };
    match client.get(&endpoint).send() {
        Ok(resp) if resp.status().is_success() => {
            let text = resp.text().unwrap_or_default();
            // Try to count models
            let count = serde_json::from_str::<serde_json::Value>(&text)
                .ok()
                .map(|v| match &v {
                    serde_json::Value::Array(a) => a.len(),
                    serde_json::Value::Object(m) => m
                        .get("data")
                        .and_then(|d| d.as_array())
                        .map(|a| a.len())
                        .unwrap_or_else(|| {
                            m.get("models")
                                .and_then(|d| d.as_array())
                                .map(|a| a.len())
                                .unwrap_or(0)
                        }),
                    _ => 0,
                })
                .unwrap_or(0);
            (
                true,
                "ok".to_string(),
                format!("{} model(s) available", count),
            )
        }
        Ok(resp) => (
            false,
            "error".to_string(),
            format!("HTTP {}", resp.status()),
        ),
        Err(e) => (false, "error".to_string(), format!("unreachable: {e}")),
    }
}

pub fn build_overview_snapshot(
    conn: &rusqlite::Connection,
    cfg: &forza_config::AppConfig,
) -> OverviewSnapshot {
    let fast = {
        let path = &cfg.database_file;
        fast_db_report(path)
    };
    let lm_endpoint = cfg.llm.url.clone();
    let lm_model = cfg.llm.model.clone();
    let (lm_ok, lm_level, lm_message) = lm_ping_blocking(&cfg.llm.url);
    // Config-derived summaries (mirror Python _configured_*_line)
    let lm_configured_load = format!(
        "ctx {} · eval {} · phys {} · flash {} · kv {}",
        cfg.llm
            .context_length
            .map(|v| v.to_string())
            .unwrap_or_else(|| "auto".into()),
        cfg.llm
            .eval_batch_size
            .map(|v| v.to_string())
            .unwrap_or_else(|| "auto".into()),
        cfg.llm
            .physical_batch_size
            .map(|v| v.to_string())
            .unwrap_or_else(|| "auto".into()),
        cfg.llm.flash_attention,
        cfg.llm.offload_kv_cache_to_gpu
    );
    let lm_configured_request = format!(
        "prompt {} · format {} · max tokens {} · temperature {} · reasoning {}",
        cfg.prompt.active,
        cfg.llm.image_format,
        cfg.llm.max_completion_tokens,
        cfg.llm.temperature,
        cfg.llm
            .reasoning_mode
            .clone()
            .unwrap_or_else(|| "auto".into())
    );
    let lm_configured_image = format!(
        "max width {} · quality {} · grayscale {}",
        cfg.image.max_width, cfg.image.encode_quality, cfg.image.grayscale
    );
    let lm_runtime_policy = format!(
        "reload if TPS < {} for {} image(s) after {}s",
        cfg.llm.performance_tps_floor,
        cfg.llm.performance_reload_streak,
        cfg.llm.performance_reload_elapsed_s
    );
    let dashboard = {
        let images: i64 = conn
            .query_row("SELECT COUNT(*) FROM image_files", [], |r| r.get(0))
            .unwrap_or(0);
        let available: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM image_files WHERE file_status='available'",
                [],
                |r| r.get(0),
            )
            .unwrap_or(0);
        let review_open: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM review_cases WHERE status='open'",
                [],
                |r| r.get(0),
            )
            .unwrap_or(0);
        (images, available, review_open)
    };
    OverviewSnapshot {
        lm_endpoint,
        lm_model: lm_model.clone(),
        lm_loaded_instance: if lm_ok {
            "checked".to_string()
        } else {
            "Not checked".to_string()
        },
        lm_configured_load,
        lm_configured_request,
        lm_configured_image,
        lm_runtime_policy,
        lm_loaded_runtime: "—".to_string(),
        lm_capabilities: "—".to_string(),
        lm_model_info: "—".to_string(),
        lm_warnings: if lm_ok {
            "None".to_string()
        } else {
            lm_message.clone()
        },
        lm_level,
        lm_message,
        lm_ok,
        db_ok: fast.ok,
        db_errors: fast.errors,
        db_warnings: fast.warnings,
        schema_state: fast.schema_state.clone(),
        database_file: cfg.database_file.display().to_string(),
        images: dashboard.0,
        available_images: dashboard.1,
        review_open: dashboard.2,
    }
}

pub use image_inventory::{ImageInventoryEntry, ImageInventoryFilter, ImageInventoryService};
