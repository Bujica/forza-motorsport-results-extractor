// Test harness: unwraps are idiomatic assertion helpers here.
#![allow(clippy::unwrap_used, clippy::expect_used)]

//! Connection contract: WAL + busy_timeout + foreign_keys ON on every
//! connection (migration plan §4.3 / docs/database.md).

use forza_db::{configure_connection, connection_pool, open_connection};

#[test]
fn configured_connection_reports_wal_and_foreign_keys() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("conn.sqlite3");
    let conn = open_connection(&path).unwrap();

    let mode: String = conn
        .query_row("PRAGMA journal_mode", [], |r| r.get(0))
        .unwrap();
    assert_eq!(mode.to_lowercase(), "wal", "journal_mode must be WAL");

    let fk: i64 = conn
        .query_row("PRAGMA foreign_keys", [], |r| r.get(0))
        .unwrap();
    assert_eq!(fk, 1, "foreign_keys must be ON");

    let timeout: i64 = conn
        .query_row("PRAGMA busy_timeout", [], |r| r.get(0))
        .unwrap();
    assert_eq!(timeout as u64, forza_db::BUSY_TIMEOUT_MS);
}

#[test]
fn pool_connections_all_satisfy_the_contract() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("pool.sqlite3");
    let pool = connection_pool(&path, 4).unwrap();

    for _ in 0..8 {
        let conn = pool.get().unwrap();
        let mode: String = conn
            .query_row("PRAGMA journal_mode", [], |r| r.get(0))
            .unwrap();
        let fk: i64 = conn
            .query_row("PRAGMA foreign_keys", [], |r| r.get(0))
            .unwrap();
        assert_eq!(mode.to_lowercase(), "wal");
        assert_eq!(fk, 1);
    }
}

#[test]
fn configure_connection_is_idempotent() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("again.sqlite3");
    let conn = rusqlite::Connection::open(&path).unwrap();
    configure_connection(&conn).unwrap();
    configure_connection(&conn).unwrap();
}
