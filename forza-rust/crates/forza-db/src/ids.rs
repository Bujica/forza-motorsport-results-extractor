//! Opaque row identities as newtypes.
//!
//! Every table id is stored as text (or integer for `run_inputs`), so without
//! these wrappers `run_id`, `image_file_id`, and `extraction_result_id` are
//! all `String` and the compiler cannot catch a swap. The types are
//! deliberately opaque: they prevent *confusion*, not malformedness —
//! validation of unknown values stays with the review queue and the doctor.

use rusqlite::types::{FromSql, FromSqlResult, ToSql, ToSqlOutput, ValueRef};

macro_rules! string_id {
    (
        $(#[$meta:meta])*
        $name:ident
    ) => {
        $(#[$meta])*
        #[derive(Debug, Clone, PartialEq, Eq, Hash)]
        #[repr(transparent)]
        pub struct $name(String);

        impl $name {
            /// Wrap an existing id (generated inside the repositories or read
            /// back from storage).
            #[must_use]
            pub fn new(id: impl Into<String>) -> Self {
                Self(id.into())
            }

            /// Borrow the stored value for SQL params, formatting, and GUI.
            #[must_use]
            pub fn as_str(&self) -> &str {
                &self.0
            }
        }

        impl AsRef<str> for $name {
            fn as_ref(&self) -> &str {
                self.as_str()
            }
        }

        impl std::borrow::Borrow<str> for $name {
            fn borrow(&self) -> &str {
                self.as_str()
            }
        }

        impl std::fmt::Display for $name {
            fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                f.write_str(self.as_str())
            }
        }

        impl ToSql for $name {
            fn to_sql(&self) -> rusqlite::Result<ToSqlOutput<'_>> {
                self.0.to_sql()
            }
        }

        impl FromSql for $name {
            fn column_result(value: ValueRef<'_>) -> FromSqlResult<Self> {
                String::column_result(value).map(Self)
            }
        }
    };
}

string_id!(
    /// `extraction_runs.id`.
    RunId
);

string_id!(
    /// `image_files.id`.
    ImageFileId
);

string_id!(
    /// `extraction_results.id`.
    ExtractionResultId
);

string_id!(
    /// `extraction_attempts.id`.
    AttemptId
);

/// `run_inputs.id` (`INTEGER PRIMARY KEY AUTOINCREMENT`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[repr(transparent)]
pub struct RunInputId(i64);

impl RunInputId {
    #[must_use]
    pub fn new(id: i64) -> Self {
        Self(id)
    }

    #[must_use]
    pub fn as_i64(self) -> i64 {
        self.0
    }
}

impl std::fmt::Display for RunInputId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl ToSql for RunInputId {
    fn to_sql(&self) -> rusqlite::Result<ToSqlOutput<'_>> {
        self.0.to_sql()
    }
}

impl FromSql for RunInputId {
    fn column_result(value: ValueRef<'_>) -> FromSqlResult<Self> {
        i64::column_result(value).map(Self)
    }
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;

    #[test]
    fn ids_round_trip_through_sqlite() {
        let conn = rusqlite::Connection::open_in_memory().unwrap();
        conn.execute_batch("CREATE TABLE t (run_id VARCHAR, input_id INTEGER)")
            .unwrap();
        let run = RunId::new("run-abc");
        let input = RunInputId::new(7);
        conn.execute(
            "INSERT INTO t (run_id, input_id) VALUES (?1, ?2)",
            rusqlite::params![run, input],
        )
        .unwrap();
        let (back_run, back_input): (RunId, RunInputId) = conn
            .query_row("SELECT run_id, input_id FROM t", [], |row| {
                Ok((row.get(0)?, row.get(1)?))
            })
            .unwrap();
        assert_eq!(back_run, run);
        assert_eq!(back_input, input);
        assert_eq!(run.as_str(), "run-abc");
        assert_eq!(format!("{run}"), "run-abc");
    }
}
