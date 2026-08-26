//! DB doctor foundation: structural checks that do not depend on
//! application-level repositories. Run-counter and review-specific checks
//! arrive with Fase 8.

use std::path::Path;

use rusqlite::Connection;

use crate::error::DbError;
use crate::migration::{SCHEMA_VERSION, SchemaStatus, schema_status, user_version};

#[derive(Debug, Clone, PartialEq)]
pub struct DoctorCheck {
    pub key: &'static str,
    pub ok: bool,
    pub detail: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DoctorReport {
    pub ok: bool,
    pub schema_status: String,
    pub user_version: i64,
    pub checks: Vec<DoctorCheck>,
}

fn integrity_check(conn: &Connection) -> Result<DoctorCheck, DbError> {
    let result: String = conn.query_row("PRAGMA integrity_check", [], |r| r.get(0))?;
    Ok(DoctorCheck {
        key: "sqlite_integrity_check",
        ok: result == "ok",
        detail: format!("integrity_check -> {result}"),
    })
}

fn foreign_key_check(conn: &Connection) -> Result<DoctorCheck, DbError> {
    let mut stmt = conn.prepare("PRAGMA foreign_key_check")?;
    let violations = stmt.query_map([], |row| {
        Ok(format!(
            "{} row {} references {}",
            row.get::<_, String>(0)?,
            row.get::<_, i64>(1)?,
            row.get::<_, String>(2)?
        ))
    })?;
    let found: Vec<String> = violations.collect::<Result<_, _>>()?;
    Ok(DoctorCheck {
        key: "foreign_key_check",
        ok: found.is_empty(),
        detail: if found.is_empty() {
            "no foreign key violations".to_string()
        } else {
            format!("{} violation(s): {}", found.len(), found.join("; "))
        },
    })
}

/// Execute the basic doctor battery against an opened connection.
pub fn run_basic_checks(conn: &Connection) -> Result<DoctorReport, DbError> {
    let checks = vec![integrity_check(conn)?, foreign_key_check(conn)?];
    let version = user_version(conn)?;
    let status = schema_state_label(conn)?;
    let ok = checks.iter().all(|c| c.ok) && status == "current";
    Ok(DoctorReport {
        ok,
        schema_status: status,
        user_version: version,
        checks,
    })
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
            checks: vec![DoctorCheck {
                key: "database_exists",
                ok: false,
                detail: "no database file or empty database".to_string(),
            }],
        }),
        _ => {
            let conn = crate::open_connection(path)?;
            run_basic_checks(&conn)
        }
    }
}
