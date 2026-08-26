//! Read queries backing the Images inventory (GUI list path).
//!
//! The derived `processing_status` mirrors
//! `forza/application/gui_read/image_reads.py`:
//! 1. latest result per image (`created_at DESC, id DESC`) maps to
//!    processing/processed_ok/processed_error/cancelled;
//! 2. otherwise, the image's latest run_input with decision != 'process'
//!    maps to skipped;
//! 3. otherwise unprocessed.

use crate::error::DbError;
use rusqlite::{Connection, Row};

#[derive(Debug, Clone, PartialEq)]
pub struct ImageInventoryRow {
    pub id: String,
    pub current_name: String,
    pub file_status: String,
    pub best_lap_status: String,
    pub processing_status: String,
    pub file_size_bytes: Option<i64>,
}

#[derive(Debug, Clone, Default)]
pub struct ImageInventoryFilter {
    /// Exact match on the derived processing status vocabulary.
    pub processing_status: Option<String>,
    /// Only images considered by this run (via run_inputs).
    pub run_id: Option<String>,
    pub best_lap_status: Option<String>,
    pub include_missing_files: bool,
}

const PROCESSING_PROJECTION: &str = "
    COALESCE(
        CASE
            WHEN lr.status IS NULL THEN NULL
            WHEN lr.status IN ('pending', 'running') THEN 'processing'
            WHEN lr.status = 'ok' THEN 'processed_ok'
            WHEN lr.status = 'cancelled' THEN 'cancelled'
            ELSE 'processed_error'
        END,
        CASE WHEN li.image_file_id IS NOT NULL THEN 'skipped' END,
        'unprocessed'
    )
";

const FROM_CLAUSE: &str = "
    FROM image_files i
    LEFT JOIN (
        SELECT image_file_id, status,
               ROW_NUMBER() OVER (
                   PARTITION BY image_file_id
                   ORDER BY created_at DESC, id DESC
               ) AS result_rank
        FROM extraction_results
        WHERE image_file_id IS NOT NULL
    ) lr ON lr.image_file_id = i.id AND lr.result_rank = 1
    LEFT JOIN (
        SELECT ri.image_file_id
        FROM run_inputs ri
        JOIN (
            SELECT image_file_id, MAX(id) AS latest_input_id
            FROM run_inputs
            WHERE image_file_id IS NOT NULL
            GROUP BY image_file_id
        ) l ON ri.id = l.latest_input_id
        WHERE ri.decision <> 'process'
    ) li ON li.image_file_id = i.id
";

fn row_to_inventory(row: &Row<'_>) -> rusqlite::Result<ImageInventoryRow> {
    Ok(ImageInventoryRow {
        id: row.get(0)?,
        current_name: row.get(1)?,
        file_status: row.get(2)?,
        best_lap_status: row.get(3)?,
        processing_status: row.get(4)?,
        file_size_bytes: row.get(5)?,
    })
}

/// List the image inventory applying the given filters.
pub fn image_inventory(
    conn: &Connection,
    filter: &ImageInventoryFilter,
) -> Result<Vec<ImageInventoryRow>, DbError> {
    let mut clauses: Vec<String> = Vec::new();
    let mut args: Vec<Box<dyn rusqlite::types::ToSql>> = Vec::new();

    if !filter.include_missing_files {
        clauses.push("i.file_status = 'available'".to_string());
    }
    if let Some(status) = &filter.processing_status {
        clauses.push(format!("{PROCESSING_PROJECTION} = ?"));
        args.push(Box::new(status.clone()));
    }
    if let Some(best) = &filter.best_lap_status {
        clauses.push("i.best_lap_status = ?".to_string());
        args.push(Box::new(best.clone()));
    }
    if let Some(run) = &filter.run_id {
        clauses.push("i.id IN (SELECT image_file_id FROM run_inputs WHERE run_id = ?)".to_string());
        args.push(Box::new(run.clone()));
    }
    let where_clause = if clauses.is_empty() {
        String::new()
    } else {
        format!("WHERE {}", clauses.join(" AND "))
    };

    let sql = format!(
        "SELECT i.id, i.current_name, i.file_status, i.best_lap_status,
                {PROCESSING_PROJECTION} AS processing_status, i.size_bytes
         {FROM_CLAUSE}
         {where_clause}
         ORDER BY LOWER(i.current_name), i.id"
    );

    let params_ref: Vec<&dyn rusqlite::types::ToSql> =
        args.iter().map(|item| item.as_ref()).collect();
    let mut stmt = conn.prepare(&sql)?;
    let rows = stmt
        .query_map(params_ref.as_slice(), row_to_inventory)?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(rows)
}
