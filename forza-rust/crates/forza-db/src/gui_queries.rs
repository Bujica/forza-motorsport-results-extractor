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
    pub race_date: Option<String>,
    pub semantic_name: Option<String>,
    pub file_hash: String,
    pub current_path: Option<String>,
    /// None = not part of a duplicate group; Some(false) = duplicate,
    /// Some(true) = canonical owner of a duplicate group.
    pub duplicate_role: Option<bool>,
}

#[derive(Debug, Clone, Default)]
pub struct ImageInventoryFilter {
    pub file_status: Option<String>,
    /// Exact match on the derived processing status vocabulary.
    pub processing_status: Option<String>,
    /// Only images considered by this run (via run_inputs).
    pub run_id: Option<String>,
    pub best_lap_status: Option<String>,
    pub inventory_filter: Option<String>,
    pub track: Option<String>,
    pub include_missing_files: bool,
}

#[allow(dead_code)]
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

#[allow(dead_code)]
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
    LEFT JOIN (
        SELECT duplicate_of_image_file_id, COUNT(*) AS cnt
        FROM image_files
        WHERE duplicate_of_image_file_id IS NOT NULL
        GROUP BY duplicate_of_image_file_id
    ) dup ON dup.duplicate_of_image_file_id = i.id
";

fn row_to_inventory(row: &Row<'_>) -> rusqlite::Result<ImageInventoryRow> {
    let duplicate_of: Option<String> = row.get(10)?;
    let is_canonical: i64 = row.get(11)?;
    Ok(ImageInventoryRow {
        id: row.get(0)?,
        current_name: row.get(1)?,
        file_status: row.get(2)?,
        best_lap_status: row.get(3)?,
        processing_status: row.get(4)?,
        file_size_bytes: row.get(5)?,
        race_date: row.get(6)?,
        semantic_name: row.get(7)?,
        file_hash: row.get(8)?,
        current_path: row.get(9)?,
        duplicate_role: if duplicate_of.is_some() {
            Some(false)
        } else if is_canonical > 0 {
            Some(true)
        } else {
            None
        },
    })
}

/// List the image inventory applying the given filters.
///
/// Python parity: first compute the filtered ID set via `_image_ids_query`
/// (including `processing_status` as a subquery filter, not a per-row
/// projection), then fetch the rows and compute `processing_status` only for
/// those IDs — matching `forza/application/gui_read/image_reads.py`.
pub fn image_inventory(
    conn: &Connection,
    filter: &ImageInventoryFilter,
) -> Result<Vec<ImageInventoryRow>, DbError> {
    // 1) Filtered IDs (no processing_status projection, just subquery filters)
    let (where_clause, args) = filtered_ids_where_clause(filter);
    let ids_sql = if where_clause.is_empty() {
        "SELECT id FROM image_files".to_string()
    } else {
        format!("SELECT id FROM image_files i {where_clause}")
    };
    let params_ref: Vec<&dyn rusqlite::types::ToSql> =
        args.iter().map(|item| item.as_ref()).collect();
    let mut stmt = conn.prepare(&ids_sql)?;
    let ids: Vec<String> = stmt
        .query_map(params_ref.as_slice(), |row| row.get(0))?
        .collect::<Result<Vec<_>, _>>()?;
    if ids.is_empty() {
        return Ok(Vec::new());
    }

    // 2) Fetch rows for those IDs with the duplicate count (no window
    // function). Chunked past the SQLite variable limit instead of one giant
    // `IN (?,?,…)` that fails the whole inventory.
    let mut rows: Vec<ImageInventoryRow> = Vec::with_capacity(ids.len());
    for chunk in crate::id_chunks(&ids) {
        if chunk.is_empty() {
            continue;
        }
        let placeholders = chunk.iter().map(|_| "?").collect::<Vec<_>>().join(",");
        let sql = format!(
            "SELECT i.id, i.current_name, i.file_status, i.best_lap_status,
                    '' AS processing_status, i.size_bytes,
                    i.race_date, i.semantic_name, i.file_hash, i.current_path,
                    i.duplicate_of_image_file_id,
                    COALESCE(dup.cnt, 0) AS is_canonical
             FROM image_files i
             LEFT JOIN (
                SELECT duplicate_of_image_file_id, COUNT(*) AS cnt
                FROM image_files
                WHERE duplicate_of_image_file_id IS NOT NULL
                GROUP BY duplicate_of_image_file_id
             ) dup ON dup.duplicate_of_image_file_id = i.id
             WHERE i.id IN ({placeholders})
             ORDER BY LOWER(i.current_name), i.id"
        );
        let mut stmt = conn.prepare(&sql)?;
        let params: Vec<&dyn rusqlite::types::ToSql> = chunk
            .iter()
            .map(|id| id as &dyn rusqlite::types::ToSql)
            .collect();
        rows.extend(
            stmt.query_map(params.as_slice(), row_to_inventory)?
                .collect::<Result<Vec<_>, _>>()?,
        );
    }

    // 3) Compute processing_status only for the returned IDs (like Python's
    //    _latest_processing_statuses which does ROW_NUMBER only for those IDs).
    let status_map = processing_status_map(conn, &ids)?;
    for row in &mut rows {
        if let Some(status) = status_map.get(&row.id) {
            row.processing_status = status.clone();
        }
    }
    Ok(rows)
}

fn filtered_ids_where_clause(
    filter: &ImageInventoryFilter,
) -> (String, Vec<Box<dyn rusqlite::types::ToSql>>) {
    let mut clauses: Vec<String> = Vec::new();
    let mut args: Vec<Box<dyn rusqlite::types::ToSql>> = Vec::new();

    if let Some(file_status) = &filter.file_status {
        clauses.push("i.file_status = ?".to_string());
        args.push(Box::new(file_status.clone()));
    } else if !filter.include_missing_files {
        clauses.push("i.file_status = 'available'".to_string());
    }
    if let Some(best) = &filter.best_lap_status {
        clauses.push("i.best_lap_status = ?".to_string());
        args.push(Box::new(best.clone()));
    }
    if let Some(run) = &filter.run_id {
        clauses.push("i.id IN (SELECT image_file_id FROM run_inputs WHERE run_id = ?)".to_string());
        args.push(Box::new(run.clone()));
    }
    if let Some(track) = &filter.track {
        clauses.push("i.id IN (SELECT image_file_id FROM lap_records WHERE track = ?)".to_string());
        args.push(Box::new(track.clone()));
    }
    if filter.inventory_filter.as_deref() == Some("duplicate") {
        clauses.push(
            "(i.duplicate_of_image_file_id IS NOT NULL OR i.id IN
            (SELECT duplicate_of_image_file_id FROM image_files
             WHERE duplicate_of_image_file_id IS NOT NULL))"
                .to_string(),
        );
    } else if filter.inventory_filter.is_some() {
        clauses.push("0".to_string());
    }
    if let Some(status) = &filter.processing_status {
        let (clause, mut sub_args) = processing_status_filter_clause(status);
        clauses.push(clause);
        args.append(&mut sub_args);
    }
    let where_clause = if clauses.is_empty() {
        String::new()
    } else {
        format!("WHERE {}", clauses.join(" AND "))
    };
    (where_clause, args)
}

fn processing_status_filter_clause(status: &str) -> (String, Vec<Box<dyn rusqlite::types::ToSql>>) {
    match status {
        "unprocessed" => (
            "i.id NOT IN (SELECT image_file_id FROM extraction_results WHERE image_file_id IS NOT NULL)
             AND i.id NOT IN (
                SELECT ri.image_file_id FROM run_inputs ri
                JOIN (SELECT image_file_id, MAX(id) AS latest_input_id FROM run_inputs WHERE image_file_id IS NOT NULL GROUP BY image_file_id) l
                  ON ri.id = l.latest_input_id
                WHERE ri.decision <> 'process'
             )"
                .to_string(),
            Vec::new(),
        ),
        "skipped" => (
            "i.id IN (
                SELECT ri.image_file_id FROM run_inputs ri
                JOIN (SELECT image_file_id, MAX(id) AS latest_input_id FROM run_inputs WHERE image_file_id IS NOT NULL GROUP BY image_file_id) l
                  ON ri.id = l.latest_input_id
                WHERE ri.decision <> 'process' AND ri.image_file_id IS NOT NULL
                  AND ri.image_file_id NOT IN (SELECT image_file_id FROM extraction_results WHERE image_file_id IS NOT NULL)
             )"
                .to_string(),
            Vec::new(),
        ),
        other => {
            let statuses: Vec<&str> = match other {
                "processing" => vec!["pending", "running"],
                "processed_ok" => vec!["ok"],
                "processed_error" => vec!["error"],
                "cancelled" => vec!["cancelled"],
                _ => vec![],
            };
            if statuses.is_empty() {
                return ("0".to_string(), Vec::new());
            }
            let placeholders = statuses.iter().map(|_| "?").collect::<Vec<_>>().join(",");
            let clause = format!(
                "i.id IN (
                    SELECT image_file_id FROM (
                        SELECT image_file_id, status,
                               ROW_NUMBER() OVER (PARTITION BY image_file_id ORDER BY created_at DESC, id DESC) AS rn
                        FROM extraction_results WHERE image_file_id IS NOT NULL
                    ) WHERE rn = 1 AND status IN ({placeholders})
                )"
            );
            let args = statuses
                .into_iter()
                .map(|s| Box::new(s.to_string()) as Box<dyn rusqlite::types::ToSql>)
                .collect();
            (clause, args)
        }
    }
}

fn processing_status_map(
    conn: &Connection,
    ids: &[String],
) -> Result<std::collections::HashMap<String, String>, DbError> {
    use std::collections::HashMap;
    let mut map: HashMap<String, String> = HashMap::new();
    // Latest result per image (window function only for the filtered IDs),
    // chunked past the SQLite variable limit.
    for chunk in crate::id_chunks(ids) {
        if chunk.is_empty() {
            continue;
        }
        let placeholders = chunk.iter().map(|_| "?").collect::<Vec<_>>().join(",");
        let sql = format!(
            "SELECT image_file_id, status FROM (
                SELECT image_file_id, status,
                       ROW_NUMBER() OVER (PARTITION BY image_file_id ORDER BY created_at DESC, id DESC) AS rn
                FROM extraction_results
                WHERE image_file_id IN ({placeholders})
            ) WHERE rn = 1"
        );
        let params: Vec<&dyn rusqlite::types::ToSql> = chunk
            .iter()
            .map(|id| id as &dyn rusqlite::types::ToSql)
            .collect();
        let mut stmt = conn.prepare(&sql)?;
        let rows = stmt.query_map(params.as_slice(), |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
        })?;
        for (image_id, status) in rows.collect::<Result<Vec<_>, _>>()? {
            let proc = match status.as_str() {
                "pending" | "running" => "processing",
                "ok" => "processed_ok",
                "error" => "processed_error",
                "cancelled" => "cancelled",
                _ => "processed_error",
            };
            map.insert(image_id, proc.to_string());
        }
    }
    // For those without a result, check run_inputs for skipped
    let missing: Vec<String> = ids
        .iter()
        .filter(|id| !map.contains_key(*id))
        .cloned()
        .collect();
    for chunk in crate::id_chunks(&missing) {
        if chunk.is_empty() {
            continue;
        }
        let placeholders2 = chunk.iter().map(|_| "?").collect::<Vec<_>>().join(",");
        let sql2 = format!(
            "SELECT ri.image_file_id FROM run_inputs ri
             JOIN (SELECT image_file_id, MAX(id) AS latest_input_id FROM run_inputs WHERE image_file_id IS NOT NULL GROUP BY image_file_id) l
               ON ri.id = l.latest_input_id
             WHERE ri.image_file_id IN ({placeholders2}) AND ri.decision <> 'process'"
        );
        let params2: Vec<&dyn rusqlite::types::ToSql> = chunk
            .iter()
            .map(|id| id as &dyn rusqlite::types::ToSql)
            .collect();
        let mut stmt2 = conn.prepare(&sql2)?;
        let rows2 = stmt2.query_map(params2.as_slice(), |row| row.get::<_, String>(0))?;
        for id in rows2.collect::<Result<Vec<_>, _>>()? {
            map.insert(id, "skipped".to_string());
        }
    }
    // Default to unprocessed
    for id in ids {
        map.entry(id.clone())
            .or_insert_with(|| "unprocessed".to_string());
    }
    Ok(map)
}

pub fn image_inventory_options(conn: &Connection) -> Result<(Vec<String>, Vec<String>), DbError> {
    let tracks = conn
        .prepare("SELECT DISTINCT track FROM lap_records WHERE track <> '' ORDER BY LOWER(track)")?
        .query_map([], |row| row.get(0))?
        .collect::<Result<Vec<String>, _>>()?;
    let runs = conn
        .prepare("SELECT id FROM extraction_runs ORDER BY created_at DESC, id DESC")?
        .query_map([], |row| row.get(0))?
        .collect::<Result<Vec<String>, _>>()?;
    Ok((tracks, runs))
}
