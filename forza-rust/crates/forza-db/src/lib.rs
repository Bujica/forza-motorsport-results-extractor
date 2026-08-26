//! SQLite persistence: connection contract, schema migration, repositories,
//! GUI read queries, and the DB doctor foundation.
//!
//! Schema DDL is generated from the audited Python baseline
//! (`schema_ddl.rs`); the schema version is tracked via `PRAGMA user_version`.

pub mod connection;
pub mod doctor;
pub mod error;
pub mod gui_queries;
pub mod image_detail;
pub mod migration;
pub mod repositories;
pub mod schema_ddl;

pub use connection::{
    BUSY_TIMEOUT_MS, SqlitePool, configure_connection, connection_pool, open_connection,
};
pub use error::DbError;
pub use gui_queries::{ImageInventoryFilter, ImageInventoryRow, image_inventory};
pub use image_detail::{
    DetailAttemptRow, DetailLapRow, DetailResultRow, ImageDetailMeta, attempts_for_image,
    image_detail_meta, laps_for_image, results_for_image,
};
pub use migration::{SCHEMA_VERSION, SchemaStatus, schema_status, upgrade};

/// Utilities for building reproducible test databases. Not intended for
/// production paths.
pub mod test_support {
    pub use crate::repositories::seed_demo_database;
}

pub mod prelude {
    pub use crate::repositories::images::{known_hashes, known_path_hashes};
}
