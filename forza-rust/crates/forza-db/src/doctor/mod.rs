//! Full DB doctor battery ported from `forza/application/db_doctor/`.
//!
//! Checks are grouped like the Python modules: SQLite integrity, status
//! vocabulary, run/input contract, image files, best-lap state, reviews,
//! artifacts, and schema drift. Filesystem-backed checks (image bytes,
//! artifact hashes) read the files referenced by database rows.

//! Checks are grouped like the Python modules in `forza/application/db_doctor/`:
//! each section lives in its own submodule behind one orchestration entry point.

mod artifact;
mod helpers;
mod images;
mod review;
mod run;
mod schema;
mod sqlite;
mod status;
mod types;

pub use types::{DoctorCheck, DoctorReport, DoctorSeverity};

use std::path::Path;

use rusqlite::Connection;

use crate::error::DbError;
use crate::migration::{SCHEMA_VERSION, SchemaStatus, schema_status, user_version};

use artifact::artifact_checks;
use images::{best_lap_status_checks, best_lap_value_checks, image_file_checks, lap_parent_checks};
use review::{review_core_checks, review_model_error_identity_checks, review_parent_flag_checks};
use run::{run_counter_checks, run_input_contract_checks, run_input_process_checks};
use schema::schema_drift_checks;
use sqlite::{foreign_key_check, integrity_check};
use status::invalid_status_values_check;

// ── Orchestration ────────────────────────────────────────────────────────────

fn schema_head_check(schema_status: &str) -> Option<DoctorCheck> {
    if schema_status == "current" {
        None
    } else {
        Some(DoctorCheck::new(
            "schema_head",
            DoctorSeverity::Error,
            format!("schema state: {schema_status}"),
            1,
        ))
    }
}

/// Execute the basic doctor battery against an opened connection.
pub fn run_basic_checks(conn: &Connection) -> Result<DoctorReport, DbError> {
    let checks = vec![integrity_check(conn)?, foreign_key_check(conn)?];
    let version = user_version(conn)?;
    let status = schema_state_label(conn)?;
    Ok(DoctorReport {
        ok: checks.iter().all(|c| c.ok) && status == "current",
        schema_status: status,
        user_version: version,
        checks,
    }
    .finish())
}

fn schema_state_label(conn: &Connection) -> Result<String, DbError> {
    let count: i64 = conn.query_row(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",
        [],
        |row| row.get(0),
    )?;
    let version = user_version(conn)?;
    if count == 0 {
        Ok("empty".to_string())
    } else if version == SCHEMA_VERSION {
        Ok("current".to_string())
    } else if version < SCHEMA_VERSION {
        Ok("needs_upgrade".to_string())
    } else {
        Ok("newer_than_build".to_string())
    }
}

/// Convenience: open + check in one call.
pub fn doctor_on_path(path: &Path) -> Result<DoctorReport, DbError> {
    match schema_status(path)? {
        SchemaStatus::Empty => Ok(DoctorReport {
            ok: false,
            schema_status: "empty".to_string(),
            user_version: 0,
            checks: vec![DoctorCheck::new(
                "database_exists",
                DoctorSeverity::Error,
                "no database file or empty database",
                1,
            )],
        }),
        _ => {
            let conn = crate::open_connection(path)?;
            run_basic_checks(&conn)
        }
    }
}

/// Full doctor battery, matching the Python check order. A non-current schema
/// short-circuits to a single `schema_head` failure like `DbDoctorService`.
pub fn run_full_doctor(conn: &Connection, schema_status: String) -> Result<DoctorReport, DbError> {
    let version = user_version(conn)?;
    let Some(schema_head) = schema_head_check(&schema_status) else {
        let mut checks = Vec::new();
        checks.push(integrity_check(conn)?);
        checks.push(foreign_key_check(conn)?);
        checks.extend(run_counter_checks(conn)?);
        checks.push(invalid_status_values_check(conn)?);
        checks.extend(run_input_contract_checks(conn)?);
        checks.extend(image_file_checks(conn)?);
        checks.extend(run_input_process_checks(conn)?);
        checks.extend(artifact_checks(conn)?);
        checks.extend(review_core_checks(conn)?);
        checks.extend(best_lap_value_checks(conn)?);
        checks.extend(review_model_error_identity_checks(conn)?);
        checks.extend(lap_parent_checks(conn)?);
        checks.extend(review_parent_flag_checks(conn)?);
        checks.extend(best_lap_status_checks(conn)?);
        checks.extend(schema_drift_checks(conn)?);

        return Ok(DoctorReport {
            ok: false,
            schema_status,
            user_version: version,
            checks,
        }
        .finish());
    };

    Ok(DoctorReport {
        ok: false,
        schema_status,
        user_version: version,
        checks: vec![schema_head],
    }
    .finish())
}
