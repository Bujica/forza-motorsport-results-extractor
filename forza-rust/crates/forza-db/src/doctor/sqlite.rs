//! SQLite integrity checks (sqlite_checks.py).

use rusqlite::Connection;

use crate::error::DbError;

use super::types::{DoctorCheck, DoctorSeverity};

// ── SQLite integrity (sqlite_checks.py) ──────────────────────────────────────

pub(super) fn integrity_check(conn: &Connection) -> Result<DoctorCheck, DbError> {
    // `PRAGMA integrity_check` emits one row per error: collect them all
    // instead of reporting only the first row.
    let mut stmt = conn.prepare("PRAGMA integrity_check")?;
    let rows: Vec<String> = stmt
        .query_map([], |r| r.get(0))?
        .collect::<Result<Vec<_>, _>>()?;
    let damaged = rows.iter().any(|r| r != "ok");
    let detail = if damaged {
        format!("integrity_check -> {}", rows.join("; "))
    } else {
        "integrity_check -> ok".to_string()
    };
    Ok(DoctorCheck::new(
        "sqlite_integrity_check",
        DoctorSeverity::Error,
        detail,
        i64::from(damaged),
    ))
}

pub(super) fn foreign_key_check(conn: &Connection) -> Result<DoctorCheck, DbError> {
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
    let count = found.len() as i64;
    let detail = if found.is_empty() {
        "no foreign key violations".to_string()
    } else {
        format!("{} violation(s): {}", found.len(), found.join("; "))
    };
    Ok(DoctorCheck::new(
        "foreign_key_violations",
        DoctorSeverity::Error,
        detail,
        count,
    ))
}
