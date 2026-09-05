//! Application services: use-case orchestration decoupled from GUI/CLI.
//!
//! Services never know widgets; they return typed results that any
//! front-end can consume.

// Unit tests assert with unwrap/expect like the other crates.
#![cfg_attr(test, allow(clippy::unwrap_used, clippy::expect_used))]

pub mod services;

/// Build identity of the whole workspace binary set: package version, git
/// hash, and build time. CLI , the GUI title, and every run row
/// carry this so a database always reveals which binary produced it.
pub const APP_VERSION: &str = concat!(
    env!("CARGO_PKG_VERSION"),
    "+g",
    env!("APP_GIT_HASH"),
    " built ",
    env!("APP_BUILD_TIME")
);

pub use services::best_laps::{
    BestLapFilter, BestLapFilterOptions, BestLapRow, BestLapSummary, apply_filters, filter_options,
    list_best_laps, summary, summary_text, to_export_rows,
};
pub use services::{
    BestLapEntry, DoctorCheckSummary, DoctorSummary, FastDbReport, ImageDebugFilter,
    ImageDetailData, ImageInventoryEntry, ImageInventoryFilter, ImageInventoryOptions,
    ImageInventoryService, OverviewSnapshot, RebuildOutcome, ReviewCaseEntry, ReviewQueueFilter,
    RunControl, RunEvent, RunParams, SettingRow, SettingsSnapshot, append_log_file,
    build_overview_snapshot, decide_case, errors_log_path, fast_db_report, ignore_case,
    list_clean_flat_entries, list_debug_cases, list_review_cases, load_debug_detail,
    load_debug_detail_by_result, load_image_detail, rebuild, reopen_case, run_doctor,
    run_full_doctor_on_path, settings_snapshot, spawn_extraction,
};
