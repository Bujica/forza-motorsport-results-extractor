//! Connection contract: every connection used by the application must be
//! initialized with WAL journaling, a busy timeout, and foreign keys ON.
//!
//! This mirrors the decision recorded in `forza-rust/docs/database.md` and the
//! migration plan (§4.3).

use std::path::Path;
use std::time::Duration;

use r2d2::Pool;
use r2d2_sqlite::{SqliteConnectionManager, SqliteConnectionManager as Manager};
use rusqlite::Connection;

use crate::error::DbError;

/// Transient-write contention window for readers during pipeline writes.
pub const BUSY_TIMEOUT_MS: u64 = 5_000;

/// Apply the mandatory per-connection contract.
pub fn configure_connection(conn: &Connection) -> Result<(), DbError> {
    conn.pragma_update(None, "journal_mode", "WAL")?;
    conn.busy_timeout(Duration::from_millis(BUSY_TIMEOUT_MS))?;
    conn.pragma_update(None, "foreign_keys", "ON")?;
    Ok(())
}

/// Open a single configured connection.
pub fn open_connection(path: &Path) -> Result<Connection, DbError> {
    let conn = Connection::open(path)?;
    configure_connection(&conn)?;
    Ok(conn)
}

pub type SqlitePool = Pool<Manager>;

/// Build a pool whose connections all satisfy the contract above.
pub fn connection_pool(path: &Path, max_size: u32) -> Result<SqlitePool, DbError> {
    let manager = SqliteConnectionManager::file(path).with_init(|conn| {
        conn.pragma_update(None, "journal_mode", "WAL")?;
        conn.busy_timeout(Duration::from_millis(BUSY_TIMEOUT_MS))?;
        conn.pragma_update(None, "foreign_keys", "ON")
    });
    let pool = Pool::builder().max_size(max_size).build(manager)?;
    Ok(pool)
}
