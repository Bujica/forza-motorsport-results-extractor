//! Database error type.

use std::fmt;

#[derive(Debug)]
pub enum DbError {
    Sqlite(rusqlite::Error),
    Pool(String),
    /// The database schema is not usable for the requested operation.
    SchemaState {
        message: String,
    },
}

impl fmt::Display for DbError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Sqlite(e) => write!(f, "sqlite error: {e}"),
            Self::Pool(m) => write!(f, "pool error: {m}"),
            Self::SchemaState { message } => write!(f, "{message}"),
        }
    }
}

impl std::error::Error for DbError {}

impl From<rusqlite::Error> for DbError {
    fn from(e: rusqlite::Error) -> Self {
        Self::Sqlite(e)
    }
}

impl From<std::io::Error> for DbError {
    fn from(e: std::io::Error) -> Self {
        Self::Pool(e.to_string())
    }
}

impl From<r2d2::Error> for DbError {
    fn from(e: r2d2::Error) -> Self {
        Self::Pool(e.to_string())
    }
}
