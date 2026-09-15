//! Page wiring: Slint callbacks grouped by page (F1 god-file split).
//! `super::run()` keeps bootstrap/geometry and calls `wire_*` below.

mod about;
mod bestlaps;
mod debug;
mod detail;
mod inventory;
mod logs;
mod maintenance;
mod responses;
mod review;
mod run;
mod settings;

pub(crate) use about::wire_about;
pub(crate) use bestlaps::wire_bestlaps;
pub(crate) use debug::wire_debug;
pub(crate) use detail::wire_detail;
pub(crate) use inventory::wire_inventory;
pub(crate) use logs::wire_logs;
pub(crate) use maintenance::wire_maintenance;
pub(crate) use responses::handle_response;
pub(crate) use review::{set_review_class_model, set_review_track_model, wire_review};
pub(crate) use run::wire_run;
pub(crate) use settings::wire_settings;
