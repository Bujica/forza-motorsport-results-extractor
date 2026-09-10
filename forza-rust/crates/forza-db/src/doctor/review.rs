//! Review-case and flag checks (review_checks.py).

use rusqlite::Connection;

use crate::error::DbError;

use super::helpers::{check_sql, scalar};
use super::types::{DoctorCheck, DoctorSeverity};

// ── Review checks (review_checks.py) ─────────────────────────────────────────

pub(super) fn review_core_checks(conn: &Connection) -> Result<Vec<DoctorCheck>, DbError> {
    let missing_flag = check_sql(
        conn,
        "open_reviews_missing_active_flag",
        DoctorSeverity::Error,
        "Every open review case must have a matching active image flag.",
        r#"
            SELECT COUNT(*)
            FROM review_cases rc
            WHERE rc.status = 'open'
              AND rc.image_file_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM image_flags f
                  WHERE f.image_file_id = rc.image_file_id
                    AND f.flag_type = rc.reason
                    AND COALESCE(f.lap_index, -1) = COALESCE(rc.lap_index, -1)
                    AND f.status = 'active'
              )
        "#,
    )?;

    let stale_flags = check_sql(
        conn,
        "stale_active_review_flags",
        DoctorSeverity::Error,
        "System review flags must resolve when their review case disappears.",
        r#"
            SELECT COUNT(*)
            FROM image_flags f
            WHERE f.status = 'active'
              AND f.created_by = 'system'
              AND f.flag_type IN (
                  'dirty_lap', 'track', 'weather',
                  'race_class', 'car', 'driver_name'
              )
              AND NOT EXISTS (
                  SELECT 1 FROM review_cases rc
                  WHERE rc.image_file_id = f.image_file_id
                    AND rc.reason = f.flag_type
                    AND COALESCE(rc.lap_index, -1) = COALESCE(f.lap_index, -1)
                    AND rc.status = 'open'
              )
        "#,
    )?;

    let invalid_reason = check_sql(
        conn,
        "review_cases_invalid_reason",
        DoctorSeverity::Error,
        "Review cases must use canonical reasons.",
        r#"
            SELECT COUNT(*) FROM review_cases
            WHERE reason NOT IN (
                'dirty_lap', 'track', 'weather',
                'race_class', 'car', 'driver_name'
            )
        "#,
    )?;

    let corrections_invalid = check_sql(
        conn,
        "review_corrections_invalid",
        DoctorSeverity::Error,
        "Review corrections must use stable source/lap/field identity and valid field names.",
        r#"
            SELECT COUNT(*)
            FROM review_corrections
            WHERE image_file_id IS NULL
               OR stable_key IS NULL
               OR stable_key = ''
               OR corrected_value IS NULL
               OR field NOT IN ('dirty', 'track', 'weather', 'race_class', 'car', 'driver')
               OR (field IN ('dirty', 'car', 'driver') AND lap_index IS NULL)
               OR (field IN ('track', 'weather', 'race_class') AND lap_index IS NOT NULL)
        "#,
    )?;

    Ok(vec![
        missing_flag,
        stale_flags,
        invalid_reason,
        corrections_invalid,
    ])
}

fn keys_containing_volatile_lap_ids(
    conn: &Connection,
    key_column: &str,
    table: &str,
) -> Result<i64, DbError> {
    let sql = format!(
        "SELECT {key_column}, lap_record_id FROM {table}
         WHERE lap_record_id IS NOT NULL"
    );
    let mut stmt = conn.prepare(&sql)?;
    let rows = stmt.query_map([], |row| {
        Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
    })?;
    let mut count = 0i64;
    for row in rows {
        let (key, lap_record_id) = row?;
        if key.contains(&lap_record_id) {
            count += 1;
        }
    }
    Ok(count)
}

pub(super) fn review_model_error_identity_checks(
    conn: &Connection,
) -> Result<Vec<DoctorCheck>, DbError> {
    let missing_decision = check_sql(
        conn,
        "model_error_missing_decision",
        DoctorSeverity::Error,
        "Model-error reviews must store the corrected field and values.",
        r#"
            SELECT COUNT(*)
            FROM review_cases
            WHERE outcome = 'model_error'
              AND (
                  decision_field IS NULL
                  OR corrected_value IS NULL
                  OR model_value IS NULL
              )
        "#,
    )?;

    let missing_evidence = check_sql(
        conn,
        "model_error_missing_raw_evidence",
        DoctorSeverity::Error,
        "Model-error reviews must remain linked to raw model evidence.",
        r#"
            SELECT COUNT(*)
            FROM review_cases rc
            LEFT JOIN extraction_results er ON er.id = rc.extraction_result_id
            LEFT JOIN extraction_attempts a ON a.id = er.accepted_attempt_id
            WHERE rc.outcome = 'model_error'
              AND (
                  er.id IS NULL
                  OR (
                      COALESCE(a.raw_response, '') = ''
                      AND NOT EXISTS (
                          SELECT 1 FROM model_artifacts ma
                          WHERE ma.extraction_result_id = er.id
                            AND ma.artifact_type = 'raw_response'
                            AND ma.is_canonical = 1
                      )
                  )
              )
        "#,
    )?;

    let review_key_count = keys_containing_volatile_lap_ids(conn, "business_key", "review_cases")?;
    let review_key_check = DoctorCheck::new(
        "review_business_key_uses_lap_record_id",
        DoctorSeverity::Error,
        "review_cases.business_key must not depend on lap_record_id.",
        review_key_count,
    );

    let noncanonical = noncanonical_review_business_keys(conn)?;
    let noncanonical_check = DoctorCheck::new(
        "review_business_key_not_canonical",
        DoctorSeverity::Error,
        "review_cases.business_key must match the current canonical review identity.",
        noncanonical,
    );

    let orphan_source = scalar(
        conn,
        r#"
            SELECT COUNT(*) FROM review_corrections
            WHERE image_file_id NOT IN (SELECT id FROM image_files)
        "#,
    )?;
    let orphan_source_check = DoctorCheck::new(
        "review_corrections_orphan_source",
        DoctorSeverity::Error,
        "review_corrections.image_file_id must reference image_files.",
        orphan_source,
    );

    let flag_key_count = keys_containing_volatile_lap_ids(conn, "flag_key", "image_flags")?;
    let flag_key_check = DoctorCheck::new(
        "flag_key_uses_lap_record_id",
        DoctorSeverity::Error,
        "image_flags.flag_key must not depend on lap_record_id.",
        flag_key_count,
    );

    Ok(vec![
        missing_decision,
        missing_evidence,
        review_key_check,
        noncanonical_check,
        orphan_source_check,
        flag_key_check,
    ])
}

/// Mirrors `review_identity._canonical_key`: a NULL lap_index renders as an
/// empty segment and the driver name is re-normalized from
/// `driver_normalized or driver` with strip + casefold.
fn canonical_business_key_for_review(
    reason: &str,
    image_file_id: &str,
    lap_index: Option<i64>,
    driver_normalized: &str,
    source_file: &str,
    best_lap: &str,
) -> String {
    let lap_scoped = ["dirty_lap", "car", "driver_name"];
    let image_scoped = ["track", "weather", "race_class"];
    let lap_segment = lap_index.map(|i| i.to_string()).unwrap_or_default();

    if lap_scoped.contains(&reason) && !image_file_id.is_empty() {
        format!("{reason}:{image_file_id}:{lap_segment}")
    } else if image_scoped.contains(&reason) && !image_file_id.is_empty() {
        format!("{reason}:{image_file_id}")
    } else if !image_file_id.is_empty() || !driver_normalized.is_empty() {
        format!("{reason}:{image_file_id}:{lap_segment}:{driver_normalized}")
    } else {
        format!("{reason}:fallback:{source_file}:{driver_normalized}:{best_lap}")
    }
}

/// Python `_normalize`: strip + casefold (approximated with `to_lowercase`,
/// which the pipeline also uses when persisting normalized names).
fn normalize_identity_text(value: &str) -> String {
    value.trim().to_lowercase()
}

fn noncanonical_review_business_keys(conn: &Connection) -> Result<i64, DbError> {
    let mut stmt = conn.prepare(
        "SELECT reason, business_key, COALESCE(image_file_id, ''), lap_index,
                COALESCE(driver_normalized, ''), COALESCE(driver, ''),
                COALESCE(source_file, ''), COALESCE(best_lap, '')
         FROM review_cases",
    )?;
    let rows = stmt.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, Option<i64>>(3)?,
            row.get::<_, String>(4)?,
            row.get::<_, String>(5)?,
            row.get::<_, String>(6)?,
            row.get::<_, String>(7)?,
        ))
    })?;

    let mut count = 0i64;
    for row in rows {
        let (
            reason,
            business_key,
            image_file_id,
            lap_index,
            driver_normalized,
            driver,
            source_file,
            best_lap,
        ) = row?;
        // Python: _normalize(row.driver_normalized or row.driver) — an empty
        // normalized value falls back to the raw driver name.
        let normalized_source = if driver_normalized.is_empty() {
            &driver
        } else {
            &driver_normalized
        };
        let expected = canonical_business_key_for_review(
            &reason,
            &image_file_id,
            lap_index,
            &normalize_identity_text(normalized_source),
            &source_file,
            &best_lap,
        );
        if business_key != expected {
            count += 1;
        }
    }
    Ok(count)
}

pub(super) fn review_parent_flag_checks(conn: &Connection) -> Result<Vec<DoctorCheck>, DbError> {
    let orphan_lap = scalar(
        conn,
        r#"
            SELECT COUNT(*) FROM review_cases
            WHERE lap_record_id IS NOT NULL
              AND lap_record_id NOT IN (SELECT id FROM lap_records)
        "#,
    )?;
    let orphan_lap_check = DoctorCheck::new(
        "review_cases_orphan_lap",
        DoctorSeverity::Error,
        "Review cases linked to missing lap rows.",
        orphan_lap,
    );

    let review_parent = check_sql(
        conn,
        "review_parent_mismatch",
        DoctorSeverity::Error,
        "Review run/source/result/lap links must describe one evidence chain.",
        r#"
            SELECT COUNT(*)
            FROM review_cases rc
            LEFT JOIN extraction_results er ON er.id = rc.extraction_result_id
            LEFT JOIN lap_records l ON l.id = rc.lap_record_id
            WHERE (
                rc.extraction_result_id IS NOT NULL
                AND (
                    er.id IS NULL
                    OR (rc.run_id IS NOT NULL AND rc.run_id IS NOT er.run_id)
                    OR (rc.image_file_id IS NOT NULL AND rc.image_file_id IS NOT er.image_file_id)
                )
            )
            OR (
                rc.lap_record_id IS NOT NULL
                AND (
                    l.id IS NULL
                    OR (rc.run_id IS NOT NULL AND rc.run_id IS NOT l.run_id)
                    OR (rc.image_file_id IS NOT NULL AND rc.image_file_id IS NOT l.image_file_id)
                    OR (
                        rc.extraction_result_id IS NOT NULL
                        AND rc.extraction_result_id IS NOT l.extraction_result_id
                    )
                )
            )
        "#,
    )?;

    let orphan_image = scalar(
        conn,
        r#"
            SELECT COUNT(*) FROM image_flags
            WHERE image_file_id NOT IN (SELECT id FROM image_files)
        "#,
    )?;
    let orphan_image_check = DoctorCheck::new(
        "flags_orphan_image",
        DoctorSeverity::Error,
        "Image flags linked to missing image files.",
        orphan_image,
    );

    let flag_parent = check_sql(
        conn,
        "flag_parent_mismatch",
        DoctorSeverity::Error,
        "Flag run/source/result/lap links must describe one evidence chain.",
        r#"
            SELECT COUNT(*)
            FROM image_flags f
            LEFT JOIN extraction_results er ON er.id = f.extraction_result_id
            LEFT JOIN lap_records l ON l.id = f.lap_record_id
            WHERE (
                f.extraction_result_id IS NOT NULL
                AND (
                    er.id IS NULL
                    OR (f.run_id IS NOT NULL AND f.run_id IS NOT er.run_id)
                    OR f.image_file_id IS NOT er.image_file_id
                )
            )
            OR (
                f.lap_record_id IS NOT NULL
                AND (
                    l.id IS NULL
                    OR (f.run_id IS NOT NULL AND f.run_id IS NOT l.run_id)
                    OR f.image_file_id IS NOT l.image_file_id
                    OR (
                        f.extraction_result_id IS NOT NULL
                        AND f.extraction_result_id IS NOT l.extraction_result_id
                    )
                )
            )
        "#,
    )?;

    let open_without_target = scalar(
        conn,
        "SELECT COUNT(*) FROM image_flags WHERE status = 'active' AND image_file_id IS NULL",
    )?;
    let open_without_target_check = DoctorCheck::new(
        "open_flags_without_target",
        DoctorSeverity::Warning,
        "Open flags without an image target.",
        open_without_target,
    );

    Ok(vec![
        orphan_lap_check,
        review_parent,
        orphan_image_check,
        flag_parent,
        open_without_target_check,
    ])
}
