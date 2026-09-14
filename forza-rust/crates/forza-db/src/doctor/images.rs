//! Image-file and lap checks (image_file_checks.py).

use std::collections::HashSet;
use std::path::Path;

use rusqlite::Connection;

use crate::error::DbError;
use forza_domain::lap::DEFAULT_DIRTY_SYMBOLS;

use super::helpers::{check_sql, check_sql_groups, scalar, sha256_file};
use super::types::{DoctorCheck, DoctorSeverity};

/// `OR`-ed `LIKE` match for any dirty marker in `column`, derived from the
/// same [`DEFAULT_DIRTY_SYMBOLS`] set the parser strips — a newly added
/// symbol is covered here automatically. `LIKE` metacharacters (`%`, `_`,
/// `\`) are escaped so a future symbol cannot widen the match.
///
/// Contains-semantics (not trailing-only) is deliberate: persisted
/// `best_lap` values are already stripped, so *any* remnant anywhere
/// signals a pipeline bug.
#[must_use]
fn dirty_marker_like(column: &str) -> String {
    DEFAULT_DIRTY_SYMBOLS
        .chars()
        .map(|c| {
            let escaped = match c {
                '%' | '_' | '\\' => format!("\\{c}"),
                _ => c.to_string(),
            };
            format!("{column} LIKE '%{escaped}%' ESCAPE '\\'")
        })
        .collect::<Vec<_>>()
        .join(" OR ")
}

/// `{sha256_hex}_{size}` via the pipeline-owned formatter — never retyped
/// here, so writer and verifier cannot desync.
fn image_file_hash(path: &Path) -> std::io::Result<String> {
    let hex = sha256_file(path)?;
    let size = std::fs::metadata(path)?.len();
    Ok(forza_pipeline::format_file_hash(&hex, size))
}

fn size_from_file_hash(value: &str) -> Option<i64> {
    let (_, size_text) = value.rsplit_once('_')?;
    size_text.parse().ok()
}

// ── Image file checks (image_file_checks.py) ─────────────────────────────────

fn available_image_file_checks(conn: &Connection) -> Result<(i64, i64), DbError> {
    let mut stmt = conn.prepare(
        "SELECT current_path, file_hash FROM image_files WHERE file_status = 'available'",
    )?;
    let rows = stmt.query_map([], |row| {
        Ok((row.get::<_, Option<String>>(0)?, row.get::<_, String>(1)?))
    })?;

    let mut missing = 0i64;
    let mut mismatched = 0i64;
    for row in rows {
        let (current_path, expected_hash) = row?;
        let Some(path_str) = current_path else {
            missing += 1;
            continue;
        };
        let path = Path::new(&path_str);
        let metadata = match std::fs::metadata(path) {
            Ok(m) if m.is_file() => m,
            _ => {
                missing += 1;
                continue;
            }
        };
        if let Some(expected_size) = size_from_file_hash(&expected_hash)
            && metadata.len() != expected_size.unsigned_abs()
        {
            mismatched += 1;
            continue;
        }
        match image_file_hash(path) {
            Err(_) => missing += 1,
            Ok(actual) if actual != expected_hash => mismatched += 1,
            Ok(_) => {}
        }
    }
    Ok((missing, mismatched))
}

pub(super) fn image_file_checks(conn: &Connection) -> Result<Vec<DoctorCheck>, DbError> {
    let (missing_files, mismatched_hashes) = available_image_file_checks(conn)?;

    let missing_metadata = check_sql(
        conn,
        "images_missing_metadata",
        DoctorSeverity::Warning,
        "Image files without physical metadata.",
        r#"
            SELECT COUNT(*) FROM image_files
            WHERE size_bytes IS NULL OR width_px IS NULL OR height_px IS NULL
        "#,
    )?;

    let path_conflicts = check_sql_groups(
        conn,
        "available_image_path_conflicts",
        DoctorSeverity::Error,
        "An available current_path may identify only one image file.",
        r#"
            SELECT current_path
            FROM image_files
            WHERE file_status = 'available' AND current_path IS NOT NULL
            GROUP BY current_path
            HAVING COUNT(*) > 1
        "#,
    )?;

    let missing_files_check = DoctorCheck::new(
        "available_images_missing_files",
        DoctorSeverity::Error,
        "Available image files must resolve to an existing current_path file.",
        missing_files,
    );
    let hash_mismatch_check = DoctorCheck::new(
        "available_images_hash_mismatch",
        DoctorSeverity::Error,
        "Available image file bytes must match their persisted file_hash.",
        mismatched_hashes,
    );

    Ok(vec![
        missing_metadata,
        path_conflicts,
        missing_files_check,
        hash_mismatch_check,
    ])
}

pub(super) fn best_lap_value_checks(conn: &Connection) -> Result<Vec<DoctorCheck>, DbError> {
    let non_positive = check_sql(
        conn,
        "best_laps_without_positive_ms",
        DoctorSeverity::Error,
        "Rows marked as best laps must have positive best_lap_ms values.",
        r#"
            SELECT
                (SELECT COUNT(*) FROM lap_records
                 WHERE is_best_lap = 1 AND COALESCE(best_lap_ms, 0) <= 0)
              + (SELECT COUNT(*) FROM external_lap_records
                 WHERE active = 1 AND COALESCE(best_lap_ms, 0) <= 0)
        "#,
    )?;

    let dirty_marker = {
        let like = dirty_marker_like("best_lap");
        check_sql(
            conn,
            "clean_lap_contains_dirty_marker",
            DoctorSeverity::Error,
            "Clean canonical lap times must not retain dirty-lap markers.",
            &format!(
                "
            SELECT COUNT(*)
            FROM lap_records
            WHERE dirty = 0
              AND ({like})
        "
            ),
        )?
    };

    Ok(vec![non_positive, dirty_marker])
}

pub(super) fn lap_parent_checks(conn: &Connection) -> Result<Vec<DoctorCheck>, DbError> {
    let orphan = scalar(
        conn,
        r#"
            SELECT COUNT(*) FROM lap_records
            WHERE image_file_id NOT IN (SELECT id FROM image_files)
        "#,
    )?;
    let orphan_check = DoctorCheck::new(
        "laps_without_image_file",
        DoctorSeverity::Error,
        "Lap rows whose image file no longer exists.",
        orphan,
    );

    let parent = check_sql(
        conn,
        "lap_parent_mismatch",
        DoctorSeverity::Error,
        "Lap run/source links must match their extraction_result.",
        r#"
            SELECT COUNT(*)
            FROM lap_records l
            JOIN extraction_results er ON er.id = l.extraction_result_id
            WHERE l.run_id IS NOT er.run_id
               OR l.image_file_id IS NOT er.image_file_id
        "#,
    )?;

    Ok(vec![orphan_check, parent])
}

pub(super) fn best_lap_status_checks(conn: &Connection) -> Result<Vec<DoctorCheck>, DbError> {
    let mut ids_with_best = HashSet::new();
    {
        let mut stmt =
            conn.prepare("SELECT image_file_id FROM lap_records WHERE is_best_lap = 1")?;
        let rows = stmt.query_map([], |row| row.get::<_, String>(0))?;
        for id in rows {
            ids_with_best.insert(id?);
        }
    }

    let mut stmt = conn.prepare("SELECT id, best_lap_status FROM image_files")?;
    let rows = stmt.query_map([], |row| {
        Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
    })?;

    let mut divergent = 0i64;
    for row in rows {
        let (image_id, status) = row?;
        let has_best = ids_with_best.contains(&image_id);
        if has_best != (status == "contributing") {
            divergent += 1;
        }
    }
    let divergent_check = DoctorCheck::new(
        "best_lap_status_divergent",
        DoctorSeverity::Warning,
        "Images marked as contributing without a best lap, or the reverse.",
        divergent,
    );

    let stale_pending = check_sql(
        conn,
        "best_lap_status_stale_pending",
        DoctorSeverity::Error,
        "Images with clean lap rows must not remain in pending best-lap status.",
        r#"
            SELECT COUNT(DISTINCT si.id)
            FROM image_files si
            JOIN lap_records lr ON lr.image_file_id = si.id
            WHERE si.best_lap_status = 'pending'
              AND si.file_status = 'available'
              AND lr.dirty = 0
              AND COALESCE(lr.best_lap_ms, 0) > 0
        "#,
    )?;

    Ok(vec![divergent_check, stale_pending])
}

#[cfg(test)]
mod tests {
    use super::dirty_marker_like;
    use forza_domain::lap::DEFAULT_DIRTY_SYMBOLS;

    #[test]
    #[allow(clippy::unwrap_used)]
    fn image_file_hash_matches_pipeline_format() {
        // Writer/verifier parity: the doctor must reproduce exactly what
        // `pipeline::file_hash` persists, or every image false-flags.
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("shot.png");
        std::fs::write(&path, b"pixels").unwrap();
        assert_eq!(
            super::image_file_hash(&path).unwrap(),
            forza_pipeline::file_hash(&path).unwrap()
        );
        assert_eq!(forza_pipeline::format_file_hash("ab", 3), "ab_3");
    }

    #[test]
    fn dirty_like_covers_every_parse_symbol() {
        // One LIKE per parse symbol — adding a symbol to the const extends
        // the doctor automatically (previously `!`/`△` were silently absent).
        let like = dirty_marker_like("best_lap");
        assert_eq!(
            like.matches("LIKE").count(),
            DEFAULT_DIRTY_SYMBOLS.chars().count()
        );
        for symbol in DEFAULT_DIRTY_SYMBOLS.chars() {
            assert!(
                like.contains(&format!("best_lap LIKE '%{symbol}%'")),
                "missing LIKE for {symbol}"
            );
        }
    }
}
