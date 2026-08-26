//! Application services: use-case orchestration decoupled from GUI/CLI.
//!
//! Services never know widgets; they return typed results that any
//! front-end can consume.

pub mod services;

pub use services::{
    BestLapEntry, DoctorSummary, ImageInventoryEntry, ImageInventoryFilter, ImageInventoryService,
    RebuildOutcome, ReviewCaseEntry, decide_case, ignore_case, list_clean_flat_entries,
    list_review_cases, rebuild, run_doctor,
};
