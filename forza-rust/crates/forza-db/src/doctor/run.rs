//! Run/input contract checks (run_checks.py).

use rusqlite::Connection;

use crate::error::DbError;

use super::helpers::{check_sql, check_sql_groups};
use super::types::{DoctorCheck, DoctorSeverity};

// ── Run checks (run_checks.py) ───────────────────────────────────────────────

pub(super) fn run_counter_checks(conn: &Connection) -> Result<Vec<DoctorCheck>, DbError> {
    let left_running: i64 = conn.query_row(
        "SELECT COUNT(*) FROM extraction_runs WHERE status='running'",
        [],
        |r| r.get(0),
    )?;

    let running_check = DoctorCheck::new(
        "runs_left_running",
        DoctorSeverity::Error,
        format!("running runs: {left_running}"),
        left_running,
    );

    let mut stmt = conn.prepare(
        "SELECT r.id, r.total_inputs, r.to_process, r.skipped, r.duplicate_count,
                r.processed, r.succeeded, r.failed, r.review_case_count,
                (SELECT COUNT(*) FROM run_inputs ri WHERE ri.run_id = r.id) as actual_inputs,
                (SELECT COUNT(*) FROM run_inputs ri WHERE ri.run_id = r.id AND ri.decision='process') as actual_to_process,
                (SELECT COUNT(*) FROM run_inputs ri WHERE ri.run_id = r.id AND ri.decision NOT IN ('process','duplicate')) as actual_skipped,
                (SELECT COUNT(*) FROM run_inputs ri WHERE ri.run_id = r.id AND ri.decision='duplicate') as actual_duplicates,
                (SELECT COUNT(*) FROM extraction_results er WHERE er.run_id = r.id) as actual_processed,
                (SELECT COUNT(*) FROM extraction_results er WHERE er.run_id = r.id AND er.status='ok') as actual_succeeded,
                (SELECT COUNT(*) FROM extraction_results er WHERE er.run_id = r.id AND er.status='error') as actual_failed,
                (SELECT COUNT(*) FROM review_cases rc WHERE rc.run_id = r.id AND rc.status='open') as actual_review_cases
         FROM extraction_runs r",
    )?;

    let rows = stmt.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, i64>(1)?,
            row.get::<_, i64>(2)?,
            row.get::<_, i64>(3)?,
            row.get::<_, i64>(4)?,
            row.get::<_, i64>(5)?,
            row.get::<_, i64>(6)?,
            row.get::<_, i64>(7)?,
            row.get::<_, i64>(8)?,
            row.get::<_, i64>(9)?,
            row.get::<_, i64>(10)?,
            row.get::<_, i64>(11)?,
            row.get::<_, i64>(12)?,
            row.get::<_, i64>(13)?,
            row.get::<_, i64>(14)?,
            row.get::<_, i64>(15)?,
            row.get::<_, i64>(16)?,
        ))
    })?;

    let mut mismatched_runs = 0i64;
    let mut mismatches = Vec::new();
    for row in rows {
        let (
            id,
            total_inputs,
            to_process,
            skipped,
            duplicate_count,
            processed,
            succeeded,
            failed,
            review_case_count,
            actual_inputs,
            actual_to_process,
            actual_skipped,
            actual_duplicates,
            actual_processed,
            actual_succeeded,
            actual_failed,
            actual_review_cases,
        ) = row?;

        let mut run_mismatches: Vec<String> = Vec::new();
        if total_inputs != actual_inputs {
            run_mismatches.push(format!(
                "total_inputs: stored={total_inputs} actual={actual_inputs}"
            ));
        }
        if to_process != actual_to_process {
            run_mismatches.push(format!(
                "to_process: stored={to_process} actual={actual_to_process}"
            ));
        }
        if skipped != actual_skipped {
            run_mismatches.push(format!("skipped: stored={skipped} actual={actual_skipped}"));
        }
        if duplicate_count != actual_duplicates {
            run_mismatches.push(format!(
                "duplicate_count: stored={duplicate_count} actual={actual_duplicates}"
            ));
        }
        if processed != actual_processed {
            run_mismatches.push(format!(
                "processed: stored={processed} actual={actual_processed}"
            ));
        }
        if succeeded != actual_succeeded {
            run_mismatches.push(format!(
                "succeeded: stored={succeeded} actual={actual_succeeded}"
            ));
        }
        if failed != actual_failed {
            run_mismatches.push(format!("failed: stored={failed} actual={actual_failed}"));
        }
        if review_case_count != actual_review_cases {
            run_mismatches.push(format!(
                "review_case_count: stored={review_case_count} actual={actual_review_cases}"
            ));
        }
        if !run_mismatches.is_empty() {
            mismatched_runs += 1;
            mismatches.push(format!("run {id}: {}", run_mismatches.join("; ")));
        }
    }

    let counter_detail = if mismatches.is_empty() {
        "all counters match".to_string()
    } else {
        format!(
            "{} mismatched run(s): {}",
            mismatched_runs,
            mismatches.join("; ")
        )
    };
    let counter_check = DoctorCheck::new(
        "run_counters_mismatch",
        DoctorSeverity::Error,
        counter_detail,
        mismatched_runs,
    );

    Ok(vec![running_check, counter_check])
}

pub(super) fn run_input_contract_checks(conn: &Connection) -> Result<Vec<DoctorCheck>, DbError> {
    let contract = check_sql(
        conn,
        "run_input_contract_invalid",
        DoctorSeverity::Error,
        "run_inputs decisions and reason fields must not be overloaded.",
        r#"
            SELECT COUNT(*)
            FROM run_inputs
            WHERE decision NOT IN (
                'process', 'skip', 'duplicate', 'missing',
                'unsupported', 'outside_input', 'hash_failed'
            )
               OR (decision <> 'process' AND process_reason IS NOT NULL)
               OR (decision = 'process' AND (skip_reason IS NOT NULL OR duplicate_kind IS NOT NULL))
               OR (decision = 'duplicate' AND duplicate_kind IS NULL)
               OR (decision <> 'duplicate' AND duplicate_kind IS NOT NULL)
               OR (duplicate_kind IS NOT NULL AND duplicate_kind NOT IN ('hash', 'batch'))
        "#,
    )?;

    let duplicate_link = check_sql(
        conn,
        "run_input_duplicate_link_invalid",
        DoctorSeverity::Error,
        "Duplicate inputs must retain valid same-run canonical hash/link evidence.",
        r#"
            SELECT COUNT(*)
            FROM run_inputs d
            LEFT JOIN run_inputs p ON p.id = d.duplicate_of_input_id
            WHERE (
                d.decision = 'duplicate'
                AND (
                    d.file_hash IS NULL
                    OR d.duplicate_of_hash IS NULL
                    OR d.file_hash <> d.duplicate_of_hash
                    OR (d.duplicate_kind = 'batch' AND d.duplicate_of_input_id IS NULL)
                    OR (
                        d.duplicate_of_input_id IS NOT NULL
                        AND (
                            p.id IS NULL
                            OR p.run_id <> d.run_id
                            OR p.file_hash <> d.duplicate_of_hash
                        )
                    )
                )
            )
            OR (
                d.decision <> 'duplicate'
                AND (
                    d.duplicate_of_hash IS NOT NULL
                    OR d.duplicate_of_input_id IS NOT NULL
                )
            )
        "#,
    )?;
    // NOTE: no input_order comparison between duplicate and canonical rows:
    // the runner records duplicate inputs before process inputs exist, so
    // the backfilled canonical link legitimately points forward in order.
    // Same-run + hash match is the evidence that matters.

    let final_runs = check_sql(
        conn,
        "final_runs_with_nonfinal_results",
        DoctorSeverity::Error,
        "Completed, failed, or cancelled runs cannot retain pending/running results.",
        r#"
            SELECT COUNT(*)
            FROM extraction_results er
            JOIN extraction_runs r ON r.id = er.run_id
            WHERE r.status IN ('completed', 'failed', 'cancelled')
              AND er.status IN ('pending', 'running')
        "#,
    )?;

    Ok(vec![contract, duplicate_link, final_runs])
}

pub(super) fn run_input_process_checks(conn: &Connection) -> Result<Vec<DoctorCheck>, DbError> {
    let preflight = check_sql(
        conn,
        "preflight_failure_created_results",
        DoctorSeverity::Error,
        "Run-level operational/preflight failures must not create extraction results.",
        r#"
            SELECT COUNT(*)
            FROM extraction_runs r
            WHERE r.operational_error_code = 'lmstudio_preflight_failed'
              AND EXISTS (
                  SELECT 1 FROM extraction_results er WHERE er.run_id = r.id
              )
        "#,
    )?;

    let without_image = check_sql(
        conn,
        "run_inputs_process_without_image_file",
        DoctorSeverity::Error,
        "run_inputs with decision=process must have image_file_id.",
        "SELECT COUNT(*) FROM run_inputs WHERE decision = 'process' AND image_file_id IS NULL",
    )?;

    let without_result = check_sql_groups(
        conn,
        "run_inputs_process_without_one_result",
        DoctorSeverity::Error,
        "run_inputs with decision=process must have exactly one extraction_result.",
        r#"
            SELECT ri.id
            FROM run_inputs ri
            LEFT JOIN extraction_results er ON er.run_input_id = ri.id
            WHERE ri.decision = 'process'
            GROUP BY ri.id
            HAVING COUNT(er.id) <> 1
        "#,
    )?;

    Ok(vec![preflight, without_image, without_result])
}

pub(super) fn result_input_parent_mismatch_check(
    conn: &Connection,
) -> Result<DoctorCheck, DbError> {
    check_sql(
        conn,
        "result_input_parent_mismatch",
        DoctorSeverity::Error,
        "Extraction result run/source links must match its run_input.",
        r#"
            SELECT COUNT(*)
            FROM extraction_results er
            JOIN run_inputs ri ON ri.id = er.run_input_id
            WHERE er.run_id IS NOT ri.run_id
               OR er.image_file_id IS NOT ri.image_file_id
        "#,
    )
}
