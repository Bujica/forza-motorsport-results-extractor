//! `review_cases` repository (insert path for seeds/tests).

use crate::error::DbError;
use rusqlite::{Connection, params};

pub struct ReviewCaseInsert<'a> {
    pub business_key: &'a str,
    pub case_number: i64,
    pub reason: &'a str,
    /// Column name is `trigger` (reserved word in SQL — must stay quoted).
    pub trigger_name: Option<&'a str>,
    pub status: &'a str,
    pub outcome: &'a str,
    pub image_file_id: Option<&'a str>,
}

pub fn insert_review_case(conn: &Connection, row: &ReviewCaseInsert<'_>) -> Result<(), DbError> {
    let id = format!("case-{}", row.case_number);
    conn.execute(
        "INSERT INTO review_cases
            (id, business_key, case_number, reason, \"trigger\", status, outcome, image_file_id, created_at)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, datetime('now'))",
        params![
            id,
            row.business_key,
            row.case_number,
            row.reason,
            row.trigger_name,
            row.status,
            row.outcome,
            row.image_file_id,
        ],
    )?;
    Ok(())
}
