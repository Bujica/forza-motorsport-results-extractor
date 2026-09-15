//! Database error type.

use std::fmt;

#[derive(Debug)]
pub enum DbError {
    Sqlite(rusqlite::Error),
    Io(std::io::Error),
    /// Phase-labeled transaction failure. The message already carries the
    /// phase and the cause text (e.g. `"COMMIT sync: <cause>"`), so it is
    /// complete without a source chain.
    Transaction(String),
    /// Connection-pool acquisition failure; the r2d2 source is preserved.
    Pool(r2d2::Error),
    /// The database schema is not usable for the requested operation.
    SchemaState {
        message: String,
    },
}

impl fmt::Display for DbError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Sqlite(e) => write!(f, "sqlite error: {e}"),
            Self::Io(e) => write!(f, "io error: {e}"),
            Self::Transaction(m) => write!(f, "{m}"),
            Self::Pool(e) => write!(f, "pool error: {e}"),
            Self::SchemaState { message } => write!(f, "{message}"),
        }
    }
}

impl std::error::Error for DbError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Sqlite(e) => Some(e),
            Self::Io(e) => Some(e),
            Self::Pool(e) => Some(e),
            Self::Transaction(_) | Self::SchemaState { .. } => None,
        }
    }
}

impl From<rusqlite::Error> for DbError {
    fn from(e: rusqlite::Error) -> Self {
        Self::Sqlite(e)
    }
}

impl From<std::io::Error> for DbError {
    fn from(e: std::io::Error) -> Self {
        Self::Io(e)
    }
}

impl From<r2d2::Error> for DbError {
    fn from(e: r2d2::Error) -> Self {
        Self::Pool(e)
    }
}
