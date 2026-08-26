//! Schema lifecycle: create-from-zero and version stamping via
//! `PRAGMA user_version`. The Rust line owns its own schema; Python-created
//! databases are never opened in production (migration plan §2.4/§4.3).

use std::path::Path;

use rusqlite::Connection;

use crate::error::DbError;
pub use crate::schema_ddl::{INDEX_DDL, SCHEMA_VERSION, TABLE_DDL};

/// Observed state of a database file relative to the expected schema.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SchemaStatus {
    /// No file, empty file, or zero tables: safe to `upgrade()`.
    Empty,
    /// `user_version == SCHEMA_VERSION` and tables exist.
    Current,
    /// A database with tables but an older/foreign version marker.
    Incompatible { found: i64 },
}

fn table_count(conn: &Connection) -> Result<i64, DbError> {
    let count: i64 = conn.query_row(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",
        [],
        |row| row.get(0),
    )?;
    Ok(count)
}

pub fn user_version(conn: &Connection) -> Result<i64, DbError> {
    let v = conn.query_row("PRAGMA user_version", [], |row| row.get(0))?;
    Ok(v)
}

/// Inspect the state of the database at `path` without modifying it.
pub fn schema_status(path: &Path) -> Result<SchemaStatus, DbError> {
    if !path.exists() {
        return Ok(SchemaStatus::Empty);
    }
    let conn = Connection::open(path)?;
    let count = table_count(&conn)?;
    let version = user_version(&conn)?;
    if count == 0 {
        Ok(SchemaStatus::Empty)
    } else if version == SCHEMA_VERSION {
        Ok(SchemaStatus::Current)
    } else {
        Ok(SchemaStatus::Incompatible { found: version })
    }
}

/// Create the full schema from scratch on an empty/new database.
///
/// Runs inside one transaction with foreign keys deferred-off (the baseline
/// schema contains mutual references), then stamps `PRAGMA user_version`.
/// Re-running on a current database is a no-op; on a populated database with
/// a different version it is refused.
pub fn upgrade(path: &Path) -> Result<(), DbError> {
    if let Some(parent) = path.parent()
        && !parent.as_os_str().is_empty()
        && !parent.exists()
    {
        std::fs::create_dir_all(parent).map_err(|e| DbError::Pool(e.to_string()))?;
    }
    let mut conn = Connection::open(path)?;

    match schema_status(path)? {
        SchemaStatus::Current => return Ok(()),
        SchemaStatus::Incompatible { found } => {
            return Err(DbError::SchemaState {
                message: format!(
                    "refusing to upgrade: database has user_version={found} but this build expects {SCHEMA_VERSION}; \
                     the Rust line creates its own databases from zero"
                ),
            });
        }
        SchemaStatus::Empty => {}
    }

    let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    tx.pragma_update(None, "foreign_keys", "OFF")?;
    for statement in TABLE_DDL {
        tx.execute_batch(statement)?;
    }
    for statement in INDEX_DDL {
        tx.execute_batch(statement)?;
    }
    tx.pragma_update(None, "user_version", SCHEMA_VERSION)?;
    tx.pragma_update(None, "foreign_keys", "ON")?;
    tx.commit()?;
    crate::configure_connection(&conn)?;
    Ok(())
}
