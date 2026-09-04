//! System review flags mirroring open review cases.
//!
//! Port of Python `ImageFlagRepository.add_flag` plus the flag-sync half of
//! `ReviewService.refresh_review_cases_in_session`: every open case with an
//! image target owns one active `system` flag (reactivated when resolved),
//! and active system flags whose case disappeared resolve. Key format matches
//! Python exactly (`lap:{img}:{type}:{idx}:{drv}:{trk}:{cls}` /
//! `image:{img}:{type}`) so `flag_key` never embeds a volatile lap id.
//!
//! Without this, `open_reviews_missing_active_flag` fails on any database
//! with open cases — the writer/checker drift the crate audit flagged.

use std::collections::HashSet;
use std::time::{SystemTime, UNIX_EPOCH};

use rusqlite::{Connection, OptionalExtension, params};

use super::reviews::{IMAGE_SCOPED, LAP_SCOPED};
use crate::error::DbError;

/// Review reasons that own system flags (Python `ReviewReason` vocabulary and
/// the doctor's `stale_active_review_flags` list).
pub const REVIEW_FLAG_TYPES: &[&str] = &[
    "dirty_lap",
    "track",
    "weather",
    "race_class",
    "car",
    "driver_name",
];

fn nanos_id(prefix: &str, counter: usize) -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    format!("{prefix}-{nanos:x}-{counter}")
}

fn flag_key_lap(
    image_file_id: &str,
    flag_type: &str,
    lap_index: i64,
    driver_normalized: &str,
    track_normalized: &str,
    race_class: &str,
) -> String {
    format!("lap:{image_file_id}:{flag_type}:{lap_index}:{driver_normalized}:{track_normalized}:{race_class}")
}

fn flag_key_image(image_file_id: &str, flag_type: &str) -> String {
    format!("image:{image_file_id}:{flag_type}")
}

struct OpenCase {
    run_id: Option<String>,
    extraction_result_id: Option<String>,
    lap_record_id: Option<String>,
    reason: String,
    lap_index: Option<i64>,
    image_file_id: String,
}

struct LapHint {
    id: String,
    run_id: String,
    extraction_result_id: Option<String>,
    lap_index: i64,
    driver_normalized: Option<String>,
    track_normalized: Option<String>,
    race_class: String,
}

fn find_lap(conn: &Connection, lap_id: &str) -> Result<Option<LapHint>, DbError> {
    conn.query_row(
        "SELECT id, run_id, extraction_result_id, lap_index,
                driver_normalized, track_normalized, race_class
         FROM lap_records WHERE id = ?1",
        params![lap_id],
        |r| {
            Ok(LapHint {
                id: r.get(0)?,
                run_id: r.get(1)?,
                extraction_result_id: r.get(2)?,
                lap_index: r.get(3)?,
                driver_normalized: r.get(4)?,
                track_normalized: r.get(5)?,
                race_class: r.get(6)?,
            })
        },
    )
    .optional()
    .map_err(DbError::from)
}

/// Ensure one active system flag per open case; resolve stale system flags.
/// Returns `(ensured, resolved)`.
pub fn sync_review_flags(conn: &Connection) -> Result<(usize, usize), DbError> {
    let cases: Vec<OpenCase> = {
        let mut stmt = conn.prepare(
            "SELECT run_id, extraction_result_id, lap_record_id, reason,
                    lap_index, image_file_id
             FROM review_cases
             WHERE status = 'open' AND image_file_id IS NOT NULL
             ORDER BY case_number",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok(OpenCase {
                run_id: r.get(0)?,
                extraction_result_id: r.get(1)?,
                lap_record_id: r.get(2)?,
                reason: r.get(3)?,
                lap_index: r.get(4)?,
                image_file_id: r.get(5)?,
            })
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(DbError::from)?
    };

    let mut desired: HashSet<String> = HashSet::new();
    let mut ensured = 0usize;
    let mut counter = 0usize;

    for case in &cases {
        // Unknown reasons are the doctor's `review_cases_invalid_reason`
        // territory; no flag vocabulary covers them.
        if !REVIEW_FLAG_TYPES.contains(&case.reason.as_str()) {
            continue;
        }
        let image_scoped = IMAGE_SCOPED.contains(&case.reason.as_str());
        debug_assert!(image_scoped || LAP_SCOPED.contains(&case.reason.as_str()));

        // Resolve the lap link for lap-scoped cases (fallback: any lap with
        // the same image + lap_index; then key/columns degrade gracefully).
        let lap: Option<LapHint> = if image_scoped {
            None
        } else if let Some(ref lap_id) = case.lap_record_id {
            match find_lap(conn, lap_id)? {
                Some(l) => Some(l),
                None => fallback_lap(conn, &case.image_file_id, case.lap_index)?,
            }
        } else {
            fallback_lap(conn, &case.image_file_id, case.lap_index)?
        };

        let (flag_key, scope, lap_index, drv, trk, cls): (
            String,
            &str,
            Option<i64>,
            Option<String>,
            Option<String>,
            Option<String>,
        ) = match &lap {
            Some(l) if !image_scoped => (
                flag_key_lap(
                    &case.image_file_id,
                    &case.reason,
                    l.lap_index,
                    l.driver_normalized.as_deref().unwrap_or(""),
                    l.track_normalized.as_deref().unwrap_or(""),
                    &l.race_class,
                ),
                "lap",
                Some(l.lap_index),
                l.driver_normalized.clone(),
                l.track_normalized.clone(),
                Some(l.race_class.clone()),
            ),
            _ => (
                flag_key_image(&case.image_file_id, &case.reason),
                "image",
                None,
                None,
                None,
                None,
            ),
        };
        // The doctor matches flags to cases on
        // `COALESCE(lap_index,-1)`: an image-scoped case (lap_index NULL)
        // must map to an image key with lap_index NULL even when the case
        // row happens to carry a lap_record_id.
        let (lap_id_link, result_id_link, run_id_link): (
            Option<String>,
            Option<String>,
            Option<String>,
        ) = match &lap {
            Some(l) if !image_scoped => (
                Some(l.id.clone()),
                l.extraction_result_id.clone(),
                case.run_id.clone().or(Some(l.run_id.clone())),
            ),
            _ => (
                None,
                case.extraction_result_id.clone(),
                case.run_id.clone(),
            ),
        };

        desired.insert(flag_key.clone());
        counter += 1;
        let fid = nanos_id("flg", counter);
        conn.execute(
            "INSERT INTO image_flags
                (id, image_file_id, run_id, extraction_result_id, lap_record_id,
                 flag_key, flag_scope, lap_index, driver_normalized, track_normalized,
                 race_class, flag_type, status, created_by, reason, created_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12,
                     'active', 'system', ?13, datetime('now'))
             ON CONFLICT(flag_key) DO UPDATE SET
                 status = 'active',
                 resolved_at = NULL,
                 run_id = COALESCE(excluded.run_id, run_id),
                 extraction_result_id = COALESCE(excluded.extraction_result_id, extraction_result_id),
                 lap_record_id = COALESCE(excluded.lap_record_id, lap_record_id),
                 lap_index = excluded.lap_index,
                 driver_normalized = COALESCE(excluded.driver_normalized, driver_normalized),
                 track_normalized = COALESCE(excluded.track_normalized, track_normalized),
                 race_class = COALESCE(excluded.race_class, race_class),
                 reason = excluded.reason",
            params![
                fid,
                case.image_file_id,
                run_id_link,
                result_id_link,
                lap_id_link,
                flag_key,
                scope,
                lap_index,
                drv,
                trk,
                cls,
                case.reason,
                case.reason,
            ],
        )?;
        ensured += 1;
    }

    // Resolve active system review flags with no matching open case (Python
    // parity: by flag_key; operator-owned flags are never touched).
    let resolved: usize;
    if desired.is_empty() {
        resolved = conn.execute(
            "UPDATE image_flags SET status = 'resolved', resolved_at = datetime('now')
             WHERE status = 'active' AND created_by = 'system'
               AND flag_type IN ('dirty_lap','track','weather','race_class','car','driver_name')",
            [],
        )?;
    } else {
        let placeholders = desired.iter().map(|_| "?").collect::<Vec<_>>().join(",");
        let sql = format!(
            "UPDATE image_flags SET status = 'resolved', resolved_at = datetime('now')
             WHERE status = 'active' AND created_by = 'system'
               AND flag_type IN ('dirty_lap','track','weather','race_class','car','driver_name')
               AND flag_key NOT IN ({placeholders})"
        );
        let mut stmt = conn.prepare(&sql)?;
        let refs: Vec<&dyn rusqlite::types::ToSql> = desired
            .iter()
            .map(|k| k as &dyn rusqlite::types::ToSql)
            .collect();
        resolved = stmt.execute(refs.as_slice())?;
    }

    Ok((ensured, resolved))
}

fn fallback_lap(
    conn: &Connection,
    image_file_id: &str,
    lap_index: Option<i64>,
) -> Result<Option<LapHint>, DbError> {
    let Some(idx) = lap_index else {
        return Ok(None);
    };
    conn.query_row(
        "SELECT id, run_id, extraction_result_id, lap_index,
                driver_normalized, track_normalized, race_class
         FROM lap_records WHERE image_file_id = ?1 AND lap_index = ?2 LIMIT 1",
        params![image_file_id, idx],
        |r| {
            Ok(LapHint {
                id: r.get(0)?,
                run_id: r.get(1)?,
                extraction_result_id: r.get(2)?,
                lap_index: r.get(3)?,
                driver_normalized: r.get(4)?,
                track_normalized: r.get(5)?,
                race_class: r.get(6)?,
            })
        },
    )
    .optional()
    .map_err(DbError::from)
}
