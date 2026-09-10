//! SQL/file helpers shared by all check modules.

use std::path::Path;

use rusqlite::Connection;
use sha2::{Digest, Sha256};

use crate::error::DbError;

use super::types::{DoctorCheck, DoctorSeverity};

// ── helpers ──────────────────────────────────────────────────────────────────

pub(super) fn scalar(conn: &Connection, sql: &str) -> Result<i64, DbError> {
    conn.query_row(sql, [], |row| row.get(0))
        .map_err(DbError::from)
}

pub(super) fn scalar_params(
    conn: &Connection,
    sql: &str,
    params: &[&dyn rusqlite::ToSql],
) -> Result<i64, DbError> {
    conn.query_row(sql, params, |row| row.get(0))
        .map_err(DbError::from)
}

pub(super) fn check_sql(
    conn: &Connection,
    key: &'static str,
    severity: DoctorSeverity,
    detail: &str,
    sql: &str,
) -> Result<DoctorCheck, DbError> {
    let count = scalar(conn, sql)?;
    Ok(DoctorCheck::new(key, severity, detail, count))
}

/// Count the groups produced by a `GROUP BY ... HAVING` query.
pub(super) fn check_sql_groups(
    conn: &Connection,
    key: &'static str,
    severity: DoctorSeverity,
    detail: &str,
    group_sql: &str,
) -> Result<DoctorCheck, DbError> {
    let count = scalar(conn, &format!("SELECT COUNT(*) FROM ({group_sql})"))?;
    Ok(DoctorCheck::new(key, severity, detail, count))
}

pub(super) fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    format!("{digest:x}")
}

pub(super) fn sha256_file(path: &Path) -> std::io::Result<String> {
    let mut file = std::fs::File::open(path)?;
    let mut hasher = Sha256::new();
    std::io::copy(&mut file, &mut hasher)?;
    Ok(format!("{:x}", hasher.finalize()))
}

pub(super) fn file_matches_size_and_sha256(
    path: &Path,
    expected_size: Option<i64>,
    expected_sha256: Option<&str>,
) -> bool {
    let (Some(expected_size), Some(expected_sha256)) = (expected_size, expected_sha256) else {
        return false;
    };
    let Ok(metadata) = std::fs::metadata(path) else {
        return false;
    };
    if !metadata.is_file() || metadata.len() != expected_size.unsigned_abs() {
        return false;
    }
    sha256_file(path).is_ok_and(|hex| hex == expected_sha256)
}
