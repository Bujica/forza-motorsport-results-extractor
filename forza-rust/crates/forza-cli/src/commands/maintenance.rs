//! Database inspection commands (`maintenance ...`).

use std::path::{Path, PathBuf};

use rusqlite::Connection;

use super::common::table_count;
use crate::APP_VERSION;
use forza_db::doctor;
use forza_db::migration::{SchemaStatus, schema_status};

pub(crate) fn cmd_db_status(db_path: &Path) -> anyhow::Result<()> {
    let status = schema_status(db_path)?;
    let label = match status {
        SchemaStatus::Empty => "empty",
        SchemaStatus::Current => "current",
        SchemaStatus::Incompatible { found } => {
            println!("database_file = {}", db_path.display());
            println!("schema_state  = incompatible (user_version={found})");
            std::process::exit(1);
        }
    };

    println!("database_file = {}", db_path.display());
    println!("schema_state  = {label}");

    if status == SchemaStatus::Empty {
        std::process::exit(1);
    }

    let conn = forza_db::open_connection(db_path)?;

    let image_files = table_count(&conn, "image_files");
    let extraction_runs = table_count(&conn, "extraction_runs");
    let extraction_results = table_count(&conn, "extraction_results");
    let extraction_attempts = table_count(&conn, "extraction_attempts");
    let lap_records = table_count(&conn, "lap_records");
    let review_cases = table_count(&conn, "review_cases");
    let review_corrections = table_count(&conn, "review_corrections");
    let image_flags = table_count(&conn, "image_flags");
    let export_artifacts = table_count(&conn, "export_artifacts");
    let reference_tracks = table_count(&conn, "reference_tracks");
    let reference_cars = table_count(&conn, "reference_cars");
    let external_record_imports = table_count(&conn, "external_record_imports");
    let external_lap_records = table_count(&conn, "external_lap_records");

    fn show(count: Option<i64>) -> String {
        count
            .map(|n| n.to_string())
            .unwrap_or_else(|| "ERR (unreadable)".to_string())
    }
    println!();
    println!("Relational store");
    println!("  image_files         : {}", show(image_files));
    println!("  extraction_runs     : {}", show(extraction_runs));
    println!("  extraction_results  : {}", show(extraction_results));
    println!("  extraction_attempts : {}", show(extraction_attempts));
    println!("  lap_records         : {}", show(lap_records));
    println!("  review_cases        : {}", show(review_cases));
    println!("  review_corrections  : {}", show(review_corrections));
    println!("  image_flags         : {}", show(image_flags));
    println!("  export_artifacts    : {}", show(export_artifacts));
    println!("  reference_tracks    : {}", show(reference_tracks));
    println!("  reference_cars      : {}", show(reference_cars));
    println!(
        "  external_record_imports : {}",
        show(external_record_imports)
    );
    println!("  external_lap_records    : {}", show(external_lap_records));

    Ok(())
}

pub(crate) fn cmd_db_doctor(db_path: &Path, json: bool) -> anyhow::Result<()> {
    let schema_label = report_schema_status(db_path)?;
    let report = if schema_label == "empty" {
        // Empty/missing DB — use the lightweight doctor that doesn't query tables.
        doctor::doctor_on_path(db_path)?
    } else {
        // Schema present — run the full battery.
        doctor::run_full_doctor(&forza_db::open_connection(db_path)?, schema_label)?
    };
    if json {
        let checks: Vec<_> = report
            .checks
            .iter()
            .map(|check| {
                serde_json::json!({
                    "key": check.key,
                    "severity": match check.severity {
                        doctor::DoctorSeverity::Error => "error",
                        doctor::DoctorSeverity::Warning => "warning",
                        doctor::DoctorSeverity::Info => "info",
                    },
                    "count": check.count,
                    "detail": check.detail,
                    "ok": check.ok,
                })
            })
            .collect();
        println!(
            "{}",
            serde_json::to_string_pretty(&serde_json::json!({
                "database_file": db_path,
                "schema_state": report.schema_status,
                "ok": report.ok,
                "checks": checks,
            }))?
        );
    } else {
        println!("forza {APP_VERSION}");
        println!("Database: {}", db_path.display());
        println!("Schema:   {}", report.schema_status);
        println!("OK:       {}", report.ok);
        for check in &report.checks {
            let status = if check.ok {
                "OK"
            } else {
                match check.severity {
                    doctor::DoctorSeverity::Error => "ERROR",
                    doctor::DoctorSeverity::Warning => "WARN",
                    doctor::DoctorSeverity::Info => "INFO",
                }
            };
            let count = check.count;
            println!(
                "[{status}] {key}: {count} - {detail}",
                key = check.key,
                detail = check.detail
            );
        }
    }
    if !report.ok {
        std::process::exit(2);
    }
    Ok(())
}

fn report_schema_status(db_path: &Path) -> anyhow::Result<String> {
    let status = schema_status(db_path)?;
    Ok(match status {
        SchemaStatus::Empty => "empty".to_string(),
        SchemaStatus::Current => "current".to_string(),
        SchemaStatus::Incompatible { found } => format!("incompatible (user_version={found})"),
    })
}

/// Verify no other connection holds the database by requesting an EXCLUSIVE lock.
fn ensure_exclusive_access(db_path: &Path) -> anyhow::Result<()> {
    let conn = Connection::open(db_path)?;
    // Try BEGIN EXCLUSIVE; COMMIT to acquire the lock.
    // On Windows the bundled SQLite may reject locking_mode=EXCLUSIVE pragma,
    // so we fall back to just BEGIN EXCLUSIVE and catch SQLITE_BUSY.
    match conn.execute("BEGIN EXCLUSIVE", []) {
        Ok(_) => {
            // COMMIT on the SAME connection that began the transaction: a
            // COMMIT on a second connection is a no-op and would hold the
            // lock until `conn` drops (longer than intended).
            let _ = conn.execute("COMMIT", []);
            Ok(())
        }
        Err(e) => {
            let msg = format!("{e}");
            if msg.contains("not a database") || msg.contains("file is not a database") {
                // Not a valid SQLite file — resetting is the legitimate fix.
                Ok(())
            } else if msg.contains("database is locked")
                || msg.contains("locked")
                || msg.contains("BUSY")
            {
                Err(anyhow::anyhow!(
                    "Refusing to reset database: {} appears to be in use by another connection (database locked). Close any running Forza processes (GUI, CLI runs, or scripts) and try again.",
                    db_path.display()
                ))
            } else {
                Err(anyhow::anyhow!(
                    "Refusing to reset database: {} appears to be in use by another connection ({e}). Close any running Forza processes (GUI, CLI runs, or scripts) and try again.",
                    db_path.display()
                ))
            }
        }
    }
}

pub(crate) fn cmd_db_reset(db_path: &Path, yes: bool) -> anyhow::Result<()> {
    let sidecars = [
        PathBuf::from(format!("{}-wal", db_path.display())),
        PathBuf::from(format!("{}-shm", db_path.display())),
    ];

    if db_path.exists() {
        ensure_exclusive_access(db_path)?;
    }

    // Check for stale WAL/SHM sidecars after exclusive lock check
    for sidecar in &sidecars {
        if sidecar.exists() {
            let name = sidecar
                .file_name()
                .and_then(|n| n.to_str())
                .unwrap_or("unknown");
            println!(
                "WARNING: {name} sidecar file present — a connection may have held the database recently.",
            );
        }
    }

    println!("This deletes:");
    for path in std::iter::once(db_path.to_path_buf()).chain(sidecars.iter().cloned()) {
        if path.exists() {
            println!("  {}", path.display());
        }
    }
    if !yes {
        // Python hard-errors here (SystemExit): a bare db-reset must fail
        // loudly, not exit 0 as if the reset happened.
        return Err(anyhow::anyhow!(
            "refusing to delete without --yes (re-run with --yes to confirm)"
        ));
    }
    for path in std::iter::once(db_path.to_path_buf()).chain(sidecars.iter().cloned()) {
        if path.exists() {
            std::fs::remove_file(&path)?;
            println!("removed {}", path.display());
        }
    }
    Ok(())
}
