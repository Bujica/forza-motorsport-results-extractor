//! SQLite persistence: connection contract, schema migration, repositories,
//! GUI read queries, and the DB doctor foundation.
//!
//! Schema DDL is generated from the audited Python baseline
//! (`schema_ddl.rs`); the schema version is tracked via `PRAGMA user_version`.

pub mod connection;
pub mod doctor;
pub mod error;
pub mod evidence;
pub mod gui_queries;
pub mod image_debug;
pub mod image_detail;
pub mod migration;
pub mod repositories;
pub mod schema_ddl;

pub use connection::{
    BUSY_TIMEOUT_MS, SqlitePool, configure_connection, connection_pool, open_connection,
};
pub use error::DbError;
pub use gui_queries::{ImageInventoryFilter, ImageInventoryRow, image_inventory};
pub use image_debug::{
    DebugAttempt, DebugExtraction, DebugLap, DebugReview, DebugRuntimeSnapshot, ImageDebugCase,
    ImageDebugDetail, get_image_debug_detail, get_image_debug_detail_by_result,
    list_image_debug_cases,
};
pub use image_detail::{
    DetailAttemptRow, DetailLapRow, DetailResultRow, ImageDetailMeta, attempts_for_image,
    image_detail_meta, laps_for_image, results_for_image,
};
pub use migration::{SCHEMA_VERSION, SchemaStatus, schema_status, upgrade};

/// Maximum bind parameters per statement chunk. The bundled SQLite allows
/// 32766 variables (older builds 999); materialized `IN (?,?,…)` lists past
/// that fail the whole query, so id-list queries run in chunks of this size.
pub const BIND_CHUNK_SIZE: usize = 10_000;

/// Split a slice into `BIND_CHUNK_SIZE` batches for chunked `IN (...)` queries.
pub fn id_chunks<T>(ids: &[T]) -> impl Iterator<Item = &[T]> {
    ids.chunks(BIND_CHUNK_SIZE)
}

/// Utilities for building reproducible test databases. Not intended for
/// production paths.
pub mod test_support {
    pub use crate::repositories::seed_demo_database;
}

pub mod prelude {
    pub use crate::repositories::images::{known_hashes, known_path_hashes};
}
