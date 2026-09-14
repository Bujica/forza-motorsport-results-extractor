//! Schema lifecycle: create-from-zero and version stamping via
//! `PRAGMA user_version`. The Rust line owns its own schema; Python-created
//! databases are never opened in production (migration plan §2.4/§4.3).

use std::path::Path;

use rusqlite::{Connection, OptionalExtension};

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

/// Outcome of [`migrate`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MigrateOutcome {
    /// Nothing to do: the database was already current (or was empty and got
    /// created from zero by [`upgrade`]).
    AlreadyCurrent,
    /// Stepped forward one or more versions, data preserved.
    Migrated { from: i64 },
}

/// Columns dropped by the v2 → v3 migration (the removed slow-streak reload
/// feature; write-never/read-never on the Rust line, so dropping is lossless
/// here — Python-written values in a shared file are discarded by design).
const V3_DROPPED_COLUMNS: &[&str] = &[
    "performance_tps_floor",
    "performance_reload_elapsed_s",
    "performance_reload_streak",
];

/// WAL sidecar paths next to `path` (`<db>-wal`, `<db>-shm`).
pub fn sidecar_paths(path: &Path) -> [std::path::PathBuf; 2] {
    [
        path.with_extension("sqlite3-wal"),
        path.with_extension("sqlite3-shm"),
    ]
}

/// Copy `path` to a timestamped backup next to it and return the backup path.
///
/// WAL sidecars are copied too when present, so the backup is restorable as
/// a unit. Never destroys: both [`migrate`] (before touching a live
/// database) and the GUI recovery flow (before recreating from zero) go
/// through here.
pub fn backup_database(path: &Path) -> Result<std::path::PathBuf, DbError> {
    let stamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let backup = path.with_extension(format!("sqlite3.bak-{stamp}"));
    std::fs::copy(path, &backup)?;
    for sidecar in sidecar_paths(path) {
        if sidecar.exists() {
            let dest = std::path::PathBuf::from(format!("{}.bak-{stamp}", sidecar.display()));
            std::fs::copy(&sidecar, &dest)?;
        }
    }
    Ok(backup)
}

/// Step an outdated database forward to [`SCHEMA_VERSION`], preserving data.
///
/// Currently knows v2 → v3 only (drop the three `performance_*` columns).
/// Unknown versions are refused with [`DbError::SchemaState`] — delete or
/// `db-reset` instead. Empty databases are created via [`upgrade`].
/// Returns [`MigrateOutcome::Migrated`] with the version stepped from.
///
/// # Errors
///
/// Returns [`DbError::SchemaState`] for unknown versions or when the
/// post-migration [`schema_status`] is not [`SchemaStatus::Current`],
/// [`DbError::Sqlite`] on DDL failures.
pub fn migrate(path: &Path) -> Result<MigrateOutcome, DbError> {
    match schema_status(path)? {
        SchemaStatus::Empty => {
            upgrade(path)?;
            Ok(MigrateOutcome::AlreadyCurrent)
        }
        SchemaStatus::Current => Ok(MigrateOutcome::AlreadyCurrent),
        SchemaStatus::Incompatible { found } => {
            if found != 2 {
                return Err(DbError::SchemaState {
                    message: format!(
                        "no migration path: database has user_version={found} but this build expects {SCHEMA_VERSION}; \
                         delete it or run `forza maintenance db-reset --yes` to recreate"
                    ),
                });
            }
            let conn = Connection::open(path)?;
            for column in V3_DROPPED_COLUMNS {
                conn.execute_batch(&format!("ALTER TABLE extraction_runs DROP COLUMN {column}"))?;
            }
            conn.pragma_update(None, "user_version", SCHEMA_VERSION)?;
            match schema_status(path)? {
                SchemaStatus::Current => Ok(MigrateOutcome::Migrated { from: found }),
                other => Err(DbError::SchemaState {
                    message: format!(
                        "migration v{found}→v{SCHEMA_VERSION} did not converge (status: {other:?}); \
                         restore the .bak file or recreate from zero"
                    ),
                }),
            }
        }
    }
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
///
/// # Errors
///
/// Returns [`DbError::SchemaState`] for a populated database whose
/// `user_version` differs from [`SCHEMA_VERSION`], [`DbError::Io`] when the
/// parent directory cannot be created, or [`DbError::Sqlite`]/
/// [`DbError::Transaction`] on DDL/seed failures.
pub fn upgrade(path: &Path) -> Result<(), DbError> {
    if let Some(parent) = path.parent()
        && !parent.as_os_str().is_empty()
        && !parent.exists()
    {
        std::fs::create_dir_all(parent)?;
    }
    let mut conn = Connection::open(path)?;

    fn backfill_perf_indexes(c: &Connection) -> Result<(), DbError> {
        for (name, sql) in [
            (
                "idx_extraction_results_image_file_created",
                "CREATE INDEX idx_extraction_results_image_file_created ON extraction_results(image_file_id, created_at DESC, id DESC)",
            ),
            (
                "idx_run_inputs_image_file_latest",
                "CREATE INDEX idx_run_inputs_image_file_latest ON run_inputs(image_file_id, id DESC)",
            ),
        ] {
            let exists: Option<String> = c
                .query_row(
                    "SELECT name FROM sqlite_master WHERE type='index' AND name=?1",
                    [name],
                    |r| r.get(0),
                )
                .optional()
                .unwrap_or(None);
            if exists.is_none() {
                // Surface backfill failures: a silent skip leaves a DB the
                // doctor later flags with no trace of the real cause.
                c.execute_batch(sql)
                    .map_err(|e| DbError::Transaction(format!("backfill index {name}: {e}")))?;
            }
        }
        Ok(())
    }

    match schema_status(path)? {
        SchemaStatus::Current => {
            // Surface seed/backfill failures instead of swallowing them: a
            // failing catalog seed yields a DB the doctor flags with no trace.
            let c = crate::open_connection(path)?;
            seed_reference_catalog(&c)?;
            backfill_perf_indexes(&c)?;
            return Ok(());
        }
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

    // NOTE: no `PRAGMA foreign_keys=OFF/ON` around the build: that pragma is
    // documented as a no-op inside a transaction, so the old toggle was a
    // false guarantee. Fresh `Connection::open` leaves FK off by default,
    // which is what the DDL build relies on; `configure_connection` enables
    // FK (plus WAL/busy-timeout) on the connection afterwards.
    let tx = conn.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    for statement in TABLE_DDL {
        tx.execute_batch(statement)?;
    }
    for statement in INDEX_DDL {
        tx.execute_batch(statement)?;
    }
    // Performance indexes for the Images inventory (not in the Python baseline but
    // critical for the Rust GUI's filtered queries).
    tx.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_extraction_results_image_file_created
         ON extraction_results(image_file_id, created_at DESC, id DESC);
         CREATE INDEX IF NOT EXISTS idx_run_inputs_image_file_latest
         ON run_inputs(image_file_id, id DESC);",
    )?;
    tx.pragma_update(None, "user_version", SCHEMA_VERSION)?;
    tx.commit()?;
    crate::configure_connection(&conn)?;
    // Seed reference catalog from embedded assets if tables are empty (first creation or legacy DB).
    let c = crate::open_connection(path)?;
    seed_reference_catalog(&c)?;
    backfill_perf_indexes(&c)?;
    Ok(())
}

/// Seed `reference_tracks` / `reference_cars` from embedded assets.
/// Idempotent and safe to call on every open: `INSERT OR IGNORE` runs
/// unconditionally inside one transaction, so a previously interrupted seed
/// (partial catalog: old code skipped when `count != 0`) resumes instead of
/// staying partial forever.
pub fn seed_reference_catalog(conn: &rusqlite::Connection) -> Result<(), crate::error::DbError> {
    if !conn.is_autocommit() {
        return Err(crate::error::DbError::SchemaState {
            message: "seed_reference_catalog requires autocommit (no outer transaction)".into(),
        });
    }
    conn.execute_batch("BEGIN IMMEDIATE")
        .map_err(|e| DbError::Transaction(format!("BEGIN IMMEDIATE: {e}")))?;
    let inner: Result<(), DbError> = (|| {
        let data = forza_domain::reference_data::embedded_reference_data();
        for name in &data.tracks {
            let id = format!("track-{}", name.to_lowercase().replace(' ', "_"));
            conn.execute(
                "INSERT OR IGNORE INTO reference_tracks (id, name, normalized_name, active, created_at, updated_at)
                 VALUES (?1, ?2, lower(?2), 1, datetime('now'), datetime('now'))",
                rusqlite::params![id, name],
            )?;
        }
        for name in &data.cars {
            let id = format!("car-{}", name.to_lowercase().replace(' ', "_"));
            conn.execute(
                "INSERT OR IGNORE INTO reference_cars (id, name, normalized_name, active, created_at, updated_at)
                 VALUES (?1, ?2, lower(?2), 1, datetime('now'), datetime('now'))",
                rusqlite::params![id, name],
            )?;
        }
        Ok(())
    })();
    match inner {
        Ok(()) => {
            conn.execute_batch("COMMIT")
                .map_err(|e| DbError::Transaction(format!("COMMIT catalog seed: {e}")))?;
            Ok(())
        }
        Err(e) => {
            let _ = conn.execute_batch("ROLLBACK");
            Err(e)
        }
    }
}
