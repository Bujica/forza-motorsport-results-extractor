//! DB doctor foundation: structural checks that do not depend on
//! application-level repositories. Run-counter and review-specific checks
//! arrive with Fase 8.

use std::path::Path;

use rusqlite::Connection;

use crate::error::DbError;
use crate::migration::{SCHEMA_VERSION, SchemaStatus, schema_status, user_version};

#[derive(Debug, Clone, PartialEq)]
pub enum DoctorSeverity {
    Error,
    Warning,
    Info,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DoctorCheck {
    pub key: &'static str,
    pub ok: bool,
    pub detail: String,
    pub severity: DoctorSeverity,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DoctorReport {
    pub ok: bool,
    pub schema_status: String,
    pub user_version: i64,
    pub checks: Vec<DoctorCheck>,
}

fn integrity_check(conn: &Connection) -> Result<DoctorCheck, DbError> {
    let result: String = conn.query_row("PRAGMA integrity_check", [], |r| r.get(0))?;
    Ok(DoctorCheck {
        key: "sqlite_integrity_check",
        ok: result == "ok",
        detail: format!("integrity_check -> {result}"),
        severity: DoctorSeverity::Error,
    })
}

fn foreign_key_check(conn: &Connection) -> Result<DoctorCheck, DbError> {
    let mut stmt = conn.prepare("PRAGMA foreign_key_check")?;
    let violations = stmt.query_map([], |row| {
        Ok(format!(
            "{} row {} references {}",
            row.get::<_, String>(0)?,
            row.get::<_, i64>(1)?,
            row.get::<_, String>(2)?
        ))
    })?;
    let found: Vec<String> = violations.collect::<Result<_, _>>()?;
    Ok(DoctorCheck {
        key: "foreign_key_check",
        ok: found.is_empty(),
        detail: if found.is_empty() {
            "no foreign key violations".to_string()
        } else {
            format!("{} violation(s): {}", found.len(), found.join("; "))
        },
        severity: DoctorSeverity::Error,
    })
}

/// Execute the basic doctor battery against an opened connection.
pub fn run_basic_checks(conn: &Connection) -> Result<DoctorReport, DbError> {
    let checks = vec![integrity_check(conn)?, foreign_key_check(conn)?];
    let version = user_version(conn)?;
    let status = schema_state_label(conn)?;
    let ok = checks.iter().all(|c| c.ok) && status == "current";
    Ok(DoctorReport {
        ok,
        schema_status: status,
        user_version: version,
        checks,
    })
}

fn schema_state_label(conn: &Connection) -> Result<String, DbError> {
    let count: i64 = conn.query_row(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",
        [],
        |row| row.get(0),
    )?;
    let version = user_version(conn)?;
    if count == 0 {
        Ok("empty".to_string())
    } else if version == SCHEMA_VERSION {
        Ok("current".to_string())
    } else if version < SCHEMA_VERSION {
        Ok("needs_upgrade".to_string())
    } else {
        Ok("newer_than_build".to_string())
    }
}

/// Convenience: open + check in one call.
pub fn doctor_on_path(path: &Path) -> Result<DoctorReport, DbError> {
    match schema_status(path)? {
        SchemaStatus::Empty => Ok(DoctorReport {
            ok: false,
            schema_status: "empty".to_string(),
            user_version: 0,
            checks: vec![DoctorCheck {
                key: "database_exists",
                ok: false,
                detail: "no database file or empty database".to_string(),
                severity: DoctorSeverity::Error,
            }],
        }),
        _ => {
            let conn = crate::open_connection(path)?;
            run_basic_checks(&conn)
        }
    }
}

pub fn run_counter_checks(conn: &Connection) -> Result<Vec<DoctorCheck>, DbError> {
    let left_running: i64 = conn.query_row(
        "SELECT COUNT(*) FROM extraction_runs WHERE status='running'",
        [],
        |r| r.get(0),
    )?;

    let running_check = DoctorCheck {
        key: "runs_left_running",
        ok: left_running == 0,
        detail: format!("running runs: {left_running}"),
        severity: DoctorSeverity::Error,
    };

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

    let mut mismatches = Vec::new();
    for row in rows {
        let (
            _id,
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

        if total_inputs != actual_inputs {
            mismatches.push(format!(
                "total_inputs: stored={total_inputs} actual={actual_inputs}"
            ));
        }
        if to_process != actual_to_process {
            mismatches.push(format!(
                "to_process: stored={to_process} actual={actual_to_process}"
            ));
        }
        if skipped != actual_skipped {
            mismatches.push(format!("skipped: stored={skipped} actual={actual_skipped}"));
        }
        if duplicate_count != actual_duplicates {
            mismatches.push(format!(
                "duplicate_count: stored={duplicate_count} actual={actual_duplicates}"
            ));
        }
        if processed != actual_processed {
            mismatches.push(format!(
                "processed: stored={processed} actual={actual_processed}"
            ));
        }
        if succeeded != actual_succeeded {
            mismatches.push(format!(
                "succeeded: stored={succeeded} actual={actual_succeeded}"
            ));
        }
        if failed != actual_failed {
            mismatches.push(format!("failed: stored={failed} actual={actual_failed}"));
        }
        if review_case_count != actual_review_cases {
            mismatches.push(format!(
                "review_case_count: stored={review_case_count} actual={actual_review_cases}"
            ));
        }
    }

    let counter_check = DoctorCheck {
        key: "run_counters_mismatch",
        ok: mismatches.is_empty(),
        detail: if mismatches.is_empty() {
            "all counters match".to_string()
        } else {
            format!(
                "{} mismatch(es): {}",
                mismatches.len(),
                mismatches.join("; ")
            )
        },
        severity: DoctorSeverity::Error,
    };

    Ok(vec![running_check, counter_check])
}

fn canonical_business_key_for_review(
    reason: &str,
    image_file_id: &str,
    lap_index: i64,
    driver_normalized: &str,
    source_file: &str,
    best_lap: &str,
) -> String {
    let lap_scoped = ["dirty_lap", "car", "driver_name"];
    let image_scoped = ["track", "weather", "race_class"];

    if lap_scoped.contains(&reason) && !image_file_id.is_empty() {
        format!("{reason}:{image_file_id}:{lap_index}")
    } else if image_scoped.contains(&reason) && !image_file_id.is_empty() {
        format!("{reason}:{image_file_id}")
    } else if !image_file_id.is_empty() || !driver_normalized.is_empty() {
        format!("{reason}:{image_file_id}:{lap_index}:{driver_normalized}")
    } else {
        let source = source_file.to_string();
        let best = best_lap.to_string();
        format!("{reason}:fallback:{source}:{driver_normalized}:{best}")
    }
}

pub fn review_business_key_checks(conn: &Connection) -> Result<Vec<DoctorCheck>, DbError> {
    let mut stmt = conn.prepare(
        "SELECT business_key, lap_record_id FROM review_cases WHERE lap_record_id IS NOT NULL",
    )?;

    let rows = stmt.query_map([], |row| {
        Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
    })?;

    let mut uses_lap_record_count = 0i64;
    for row in rows {
        let (business_key, lap_record_id) = row?;
        if business_key.contains(&lap_record_id) {
            uses_lap_record_count += 1;
        }
    }

    let key_check = DoctorCheck {
        key: "review_business_key_uses_lap_record_id",
        ok: uses_lap_record_count == 0,
        detail: format!("keys containing volatile lap_record_id: {uses_lap_record_count}"),
        severity: DoctorSeverity::Error,
    };

    let mut stmt2 = conn.prepare(
        "SELECT id, reason, business_key, image_file_id, lap_index, driver_normalized, source_file, best_lap
         FROM review_cases",
    )?;

    let rows2 = stmt2.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, String>(3)?,
            row.get::<_, i64>(4)?,
            row.get::<_, String>(5)?,
            row.get::<_, String>(6)?,
            row.get::<_, String>(7)?,
        ))
    })?;

    let mut not_canonical_count = 0i64;
    for row in rows2 {
        let (
            _id,
            reason,
            business_key,
            image_file_id,
            lap_index,
            driver_normalized,
            source_file,
            best_lap,
        ) = row?;
        let expected = canonical_business_key_for_review(
            &reason,
            &image_file_id,
            lap_index,
            &driver_normalized,
            &source_file,
            &best_lap,
        );
        if business_key != expected {
            not_canonical_count += 1;
        }
    }

    let canonical_check = DoctorCheck {
        key: "review_business_key_not_canonical",
        ok: not_canonical_count == 0,
        detail: format!("non-canonical keys: {not_canonical_count}"),
        severity: DoctorSeverity::Error,
    };

    Ok(vec![key_check, canonical_check])
}

pub fn run_full_doctor(conn: &Connection, schema_status: String) -> Result<DoctorReport, DbError> {
    let checks = vec![
        integrity_check(conn)?,
        foreign_key_check(conn)?,
        DoctorCheck {
            key: "schema_state",
            ok: schema_status == "current",
            detail: format!("schema status: {schema_status}"),
            severity: DoctorSeverity::Info,
        },
    ];

    let counter_checks = run_counter_checks(conn)?;
    let review_checks = review_business_key_checks(conn)?;

    let all_checks: Vec<DoctorCheck> = checks
        .into_iter()
        .chain(counter_checks)
        .chain(review_checks)
        .collect();

    let ok = all_checks.iter().all(|c| c.ok) && schema_status == "current";

    Ok(DoctorReport {
        ok,
        schema_status,
        user_version: user_version(conn)?,
        checks: all_checks,
    })
}
