//! Application services: use-case orchestration decoupled from GUI/CLI.
//!
//! Services never know widgets; they return typed results that any
//! front-end can consume.

// Unit tests assert with unwrap/expect like the other crates.
#![cfg_attr(test, allow(clippy::unwrap_used, clippy::expect_used))]

pub mod services;

pub use services::{
    BestLapEntry, DoctorSummary, ImageDebugFilter, ImageDetailData, ImageInventoryEntry,
    ImageInventoryFilter, ImageInventoryService, RebuildOutcome, ReviewCaseEntry, RunControl,
    RunEvent, RunParams, SettingRow, SettingsSnapshot, decide_case, ignore_case,
    list_clean_flat_entries, list_debug_cases, list_review_cases, load_debug_detail,
    load_debug_detail_by_result, load_image_detail, rebuild, run_doctor, settings_snapshot,
    spawn_extraction,
};
