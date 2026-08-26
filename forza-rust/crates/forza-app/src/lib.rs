//! Application services: use-case orchestration decoupled from GUI/CLI.
//!
//! Services never know widgets; they return typed results that any
//! front-end can consume.

pub mod services;

pub use services::{ImageInventoryEntry, ImageInventoryFilter, ImageInventoryService};
