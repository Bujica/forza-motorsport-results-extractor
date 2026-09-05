//! `forza` CLI — essential operational commands (migration plan §4.8).

use std::path::{Path, PathBuf};

use clap::{Parser, Subcommand};
use forza_db::doctor;
use forza_db::migration::{SchemaStatus, schema_status, upgrade};
use rusqlite::Connection;

/// Build identity shared with the GUI and stamped into every run row.
pub const APP_VERSION: &str = forza_app::APP_VERSION;

#[derive(Parser)]
#[command(
    name = "forza",
    version = APP_VERSION,
    about = "Forza Motorsport Results Extractor — extract best laps from screenshots and export clean reports"
)]
struct Cli {
    /// Path to the configuration file.
    #[arg(long, default_value = "forza_config.ini")]
    config: PathBuf,

    /// Enable verbose debug output (display only; never changes parsing).
    #[arg(long)]
    debug: bool,

    /// Strict config parsing: abort on the first invalid value instead of
    /// falling back to defaults with a warning.
    #[arg(long)]
    strict: bool,

    /// Subcommand to run.
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Launch the graphical interface (PySide6 desktop app).
    Gui,
    /// Process screenshots through the live extraction pipeline.
    ///
    /// Without flags: process all new screenshots in the input folder.
    /// With --dry-run: list new images that would be processed, no LLM calls.
    /// With --force: reprocess all images currently in input_dir.
    /// With --retry-errors: reprocess only images whose latest result is error.
    /// With --limit N: process only the first N input images.
    Run {
        /// Plan the run without contacting LM Studio or persisting results.
        #[arg(long)]
        dry_run: bool,
        /// Reprocess images even when the database already knows them.
        #[arg(long)]
        force: bool,
        #[arg(long)]
        retry_errors: bool,
        /// Cap the number of processable images.
        #[arg(long)]
        limit: Option<usize>,
    },
    /// Recompute best laps and review cases without model calls.
    ///
    /// Regenerate reports from the current SQLite state.
    /// Applies persisted review corrections before recomputing best-lap winners.
    Rebuild,
    /// Export the clean best-lap table to CSV or PDF report.
    ///
    /// Without flags: write CSV to output/exports/results.csv.
    /// With --out PATH: write to the given destination path.
    /// With --pdf: render a styled PDF report instead of CSV.
    Export {
        /// Destination CSV path.
        #[arg(long)]
        out: Option<PathBuf>,
        /// Render a PDF report instead of CSV.
        #[arg(long)]
        pdf: bool,
    },
    /// Validate the configuration file and print a report.
    ConfigCheck,
    /// Database maintenance operations (read-only unless --yes).
    ///
    /// - db-status: inspect the relational database (read-only).
    /// - db-doctor: run read-only relational integrity checks before reruns or releases.
    /// - db-doctor --json: emit the same DB Doctor checks as structured JSON.
    /// - db-upgrade: create the database or apply pending migrations.
    /// - db-reset --yes: delete the configured SQLite database before rebuilding.
    #[command(subcommand)]
    Maintenance(MaintenanceCommand),
}

#[derive(Subcommand)]
enum MaintenanceCommand {
    /// Inspect the relational database (read-only).
    ///
    /// Shows schema state and row counts for all relational tables.
    #[command(name = "db-status")]
    Status,
    /// Run read-only relational integrity checks before reruns or releases.
    ///
    /// Outputs multi-severity report (ERROR/WARN/INFO).
    /// With --json: emit the same checks as structured JSON.
    #[command(name = "db-doctor")]
    Doctor {
        /// Emit the report as JSON.
        #[arg(long)]
        json: bool,
    },
    /// Create the database or apply pending migrations.
    ///
    /// Refuses unmanaged databases (tables present but no migration tracking).
    #[command(name = "db-upgrade")]
    Upgrade,
    /// Delete the configured SQLite database before rebuilding a clean schema.
    ///
    /// Checks exclusive lock to avoid deleting an in-use database.
    /// Requires --yes to confirm.
    #[command(name = "db-reset")]
    Reset {
        /// Skip the confirmation prompt.
        #[arg(long)]
        yes: bool,
    },
    /// Backfill missing extraction evidence on rows produced by older builds.
    ///
    /// Fills result prompt_snapshot_id, attempt runtime_snapshot_id, and
    /// recomputes attempt request_hash from the persisted columns using the
    /// canonical implementation. Non-destructive: only touches rows that fail
    /// the corresponding DB doctor checks.
    #[command(name = "db-heal")]
    Heal,
}

/// Resolve the configured database path. Bare relative paths are resolved
/// against the config file's directory, not the process CWD — otherwise
/// `forza --config /other/dir/forza_config.ini db-status` silently opens
/// `./data/forza.sqlite3` instead of `/other/dir/data/forza.sqlite3`.
fn resolve_db_path(config_path: &Path, configured: PathBuf) -> PathBuf {
    if configured.is_absolute() {
        return configured;
    }
    match config_path.parent() {
        Some(parent) if !parent.as_os_str().is_empty() => parent.join(configured),
        _ => configured,
    }
}

fn database_file(config_path: &Path) -> PathBuf {
    match forza_config::load_config(config_path, false) {
        Ok((cfg, _)) => resolve_db_path(config_path, cfg.database_file),
        Err(_) => PathBuf::from("data/forza.sqlite3"),
    }
}

/// Count rows in a table; `None` when the table is missing/unreadable (never
/// conflate corruption with "empty" — callers print ERR instead of 0).
fn table_count(conn: &Connection, name: &str) -> Option<i64> {
    conn.query_row(&format!("SELECT COUNT(*) FROM \"{name}\""), [], |r| {
        r.get(0)
    })
    .ok()
}

fn cmd_config_check(config_path: &Path) -> anyhow::Result<()> {
    // Lenient load so every problem is reported, but ANY parse warning fails
    // the check: previously `workers=abc` warned, defaulted to 1, and still
    // printed "OK" with exit 0.
    let (cfg, warnings) = forza_config::load_config(config_path, false)?;
    for warning in &warnings {
        println!("warning: {warning}");
    }
    let validation = forza_config::validate_config(&cfg);
    if warnings.is_empty() && validation.is_ok() {
        println!("config-check: OK");
        println!("  database_file = {}", cfg.database_file.display());
        println!("  input_dir     = {}", cfg.input_dir.display());
        return Ok(());
    }
    eprintln!("config-check failed:");
    for warning in &warnings {
        eprintln!("  - config value ignored: {warning}");
    }
    if let Err(errors) = validation {
        for error in errors {
            eprintln!("  - {error}");
        }
    }
    std::process::exit(1);
}

fn cmd_db_status(db_path: &Path) -> anyhow::Result<()> {
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

fn cmd_db_doctor(db_path: &Path, json: bool) -> anyhow::Result<()> {
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

fn cmd_db_reset(db_path: &Path, yes: bool) -> anyhow::Result<()> {
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

fn cmd_run(
    config_path: &Path,
    strict: bool,
    dry_run: bool,
    force: bool,
    retry_errors: bool,
    limit: Option<usize>,
) -> anyhow::Result<()> {
    let cfg = load_validated_config(config_path, strict)?;
    if force && retry_errors {
        return Err(anyhow::anyhow!(
            "--force and --retry-errors cannot be combined."
        ));
    }
    if !dry_run {
        return cmd_live_run(&cfg, force, retry_errors, limit);
    }

    let conn = forza_db::open_connection(&cfg.database_file)?;

    // Retry mode replaces discovery: only images whose latest result is
    // still `error` are selected (Python `_retry_error_discovery`).
    let mut inventory_empty = false;
    let mut plan = if retry_errors {
        let failed = forza_db::repositories::images::list_failed_images_for_retry(&conn)?;
        let mut new_images = Vec::new();
        for (path, hash) in failed {
            let candidate = PathBuf::from(&path);
            if candidate.exists() {
                let live_hash = forza_pipeline::file_hash(&candidate).unwrap_or(hash);
                new_images.push(forza_pipeline::planning::DiscoveredImage {
                    path: candidate,
                    file_hash: live_hash,
                });
            }
        }
        println!("retry_errors = {} image(s) selected", new_images.len());
        forza_pipeline::planning::ImageDiscoveryPlan {
            total: new_images.len(),
            new_images,
            duplicates: Vec::new(),
            existing_images: Vec::new(),
            skipped_images: Vec::new(),
        }
    } else {
        let known_paths = forza_db::repositories::images::known_path_hashes(&conn)?;
        let known_hashes = forza_db::repositories::images::known_hashes(&conn)?;

        inventory_empty = known_hashes.is_empty() && known_paths.is_empty();
        let images = forza_pipeline::find_images(&cfg.input_dir);
        forza_pipeline::plan_images(&images, &known_hashes, &known_paths, force)?
    };

    if let Some(limit) = limit {
        plan.new_images.truncate(limit);
    }

    println!("input_dir     = {}", cfg.input_dir.display());
    println!("total files   = {}", plan.total);
    if inventory_empty {
        println!("inventory     = empty (first run: nothing cached yet)");
    }
    println!("new           = {}", plan.process_count());
    println!(
        "cached dupes  = {}",
        plan.duplicates
            .iter()
            .filter(|d| d.reason == "cached")
            .count()
    );
    println!(
        "batch dupes   = {}",
        plan.duplicates
            .iter()
            .filter(|d| d.reason == "batch")
            .count()
    );
    println!("existing      = {}", plan.existing_images.len());
    println!("skipped       = {}", plan.skipped_images.len());

    if dry_run {
        println!();
        println!("-- dry run plan --");
        for image in &plan.new_images {
            println!(
                "  PROCESS  {}  [{}]",
                image.path.display(),
                &image.file_hash[..12]
            );
        }
        for dup in &plan.duplicates {
            match dup.reason.as_str() {
                "batch" => println!(
                    "  DUP-BATCH {}  (matches {})",
                    dup.path.display(),
                    dup.canonical_name
                ),
                _ => println!("  DUP-CACHED {}", dup.path.display()),
            }
        }
        for existing in &plan.existing_images {
            println!("  EXISTING {}", existing.path.display());
        }
        for skipped in &plan.skipped_images {
            println!("  SKIP[{}] {}", skipped.reason, skipped.path.display());
        }
    }
    Ok(())
}

fn cmd_live_run(
    cfg: &forza_config::AppConfig,
    force: bool,
    retry_errors: bool,
    limit: Option<usize>,
) -> anyhow::Result<()> {
    use std::sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    };

    let mut params = forza_app::RunParams::from_config(cfg, force);
    params.retry_errors = retry_errors;
    params.max_images = limit;
    // File logging (Python `logging_setup` parity): the CLI mirrors the GUI
    // and persists its event stream to the configured log file.
    let log_file = params.log_file.clone();
    let errors_file = forza_app::errors_log_path(&params.log_file);
    let failed = Arc::new(AtomicBool::new(false));
    let failed_for_events = Arc::clone(&failed);
    let cancelled = Arc::new(AtomicBool::new(false));
    let cancelled_for_events = Arc::clone(&cancelled);
    let handle = forza_app::spawn_extraction(params, forza_app::RunControl::new(), move |event| {
        match event {
            forza_app::RunEvent::Started { run_id, total } => {
                let line = format!("started: run={run_id} total={total}");
                println!("{line}");
                forza_app::append_log_file(&log_file, &line);
            }
            forza_app::RunEvent::Plan {
                new,
                cached,
                batch,
                existing,
                skipped,
            } => {
                let line = format!(
                    "plan: new={new} cached={cached} batch={batch} existing={existing} skipped={skipped}"
                );
                println!("{line}");
                forza_app::append_log_file(&log_file, &line);
            }
            forza_app::RunEvent::ImageStarted { name } => {
                let line = format!("processing: {name}");
                println!("{line}");
                forza_app::append_log_file(&log_file, &line);
            }
            forza_app::RunEvent::ImageDone { name, ok, laps } => {
                let line = format!("done: {name} ok={ok} laps={laps}");
                println!("{line}");
                forza_app::append_log_file(&log_file, &line);
                if !ok {
                    forza_app::append_log_file(&errors_file, &line);
                }
            }
            forza_app::RunEvent::Progress { done, total } => println!("progress: {done}/{total}"),
            forza_app::RunEvent::Log(message) => {
                println!("log: {message}");
                forza_app::append_log_file(&log_file, &message);
            }
            forza_app::RunEvent::Finished {
                cancelled,
                processed,
                succeeded,
                failed,
                elapsed_s,
            } => {
                if failed > 0 {
                    failed_for_events.store(true, Ordering::Relaxed);
                }
                if cancelled {
                    cancelled_for_events.store(true, Ordering::Relaxed);
                }
                let line = format!(
                    "finished: cancelled={cancelled} processed={processed} succeeded={succeeded} failed={failed} elapsed_s={elapsed_s:.3}"
                );
                println!("{line}");
                forza_app::append_log_file(&log_file, &line);
                if failed > 0 {
                    forza_app::append_log_file(&errors_file, &line);
                }
            }
            forza_app::RunEvent::Failed(message) => {
                failed_for_events.store(true, Ordering::Relaxed);
                eprintln!("run failed: {message}");
                let line = format!("run failed: {message}");
                forza_app::append_log_file(&log_file, &line);
                forza_app::append_log_file(&errors_file, &line);
            }
        }
    });
    handle
        .join()
        .map_err(|_| anyhow::anyhow!("extraction thread panicked"))?;
    // Python parity: cancelled → 130. Per-image failures still fail the
    // command (stricter than Python, which exits 0) so scripts notice them.
    if cancelled.load(Ordering::Relaxed) {
        std::process::exit(130);
    }
    if failed.load(Ordering::Relaxed) {
        return Err(anyhow::anyhow!("extraction completed with failures"));
    }
    Ok(())
}

/// Lenient load + print warnings, then enforce `validate_config`: run /
/// rebuild / export must not proceed with `workers=0`, `image_format=bmp`
/// etc. into obscure downstream failures when `config-check` already fails.
fn load_validated_config(
    config_path: &Path,
    strict: bool,
) -> anyhow::Result<forza_config::AppConfig> {
    let (cfg, warnings) = forza_config::load_config(config_path, strict)?;
    for warning in &warnings {
        eprintln!("warning: {warning}");
    }
    match forza_config::validate_config(&cfg) {
        Ok(()) => Ok(cfg),
        Err(errors) => Err(anyhow::anyhow!(
            "configuration invalid (run `forza config-check`): {}",
            errors.join("; ")
        )),
    }
}

fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();
    let debug = cli.debug;
    let strict = cli.strict;
    let _ = debug;
    match cli.command {
        Command::Gui => forza_gui::run(&cli.config),
        Command::Rebuild => {
            let cfg = load_validated_config(&cli.config, strict)?;
            let conn = forza_db::open_connection(&cfg.database_file)?;
            let outcome = forza_app::services::rebuild::rebuild(&conn, &cfg.gamertag)
                .map_err(|e| anyhow::anyhow!(e))?;
            println!(
                "rebuild: {} best-lap winner(s); reviews +{} kept {} auto-resolved {} (flags +{}/{})",
                outcome.best_lap_winners,
                outcome.review_inserted,
                outcome.review_kept,
                outcome.review_auto_resolved,
                outcome.flags_ensured,
                outcome.flags_resolved
            );
            Ok(())
        }
        Command::Run {
            dry_run,
            force,
            retry_errors,
            limit,
        } => cmd_run(&cli.config, strict, dry_run, force, retry_errors, limit),
        Command::Export { out, pdf } => {
            let cfg = load_validated_config(&cli.config, strict)?;
            let conn = forza_db::open_connection(&cfg.database_file)?;
            let rows =
                forza_db::repositories::laps::list_clean_flat(&conn, &cfg.gamertag.to_lowercase())?;
            if rows.is_empty() {
                println!("export: no best-lap rows to export");
                return Ok(());
            }
            let export_rows: Vec<forza_output::csv::ExportRow> = rows
                .iter()
                .map(|r| forza_output::csv::ExportRow {
                    track: r.track.clone(),
                    race_class: r.race_class.clone(),
                    weather: r.weather.clone(),
                    temp_f: r.temp_f,
                    temp_c: r.temp_c,
                    driver: r.driver.clone(),
                    car: r.car.clone(),
                    best_lap: r.best_lap.clone(),
                    best_lap_ms: r.best_lap_ms,
                    dirty: r.dirty,
                    source_file: r.source_file.clone(),
                    race_date: r.race_date.clone(),
                    image_format: r.image_format.clone(),
                    width_px: r.width_px,
                    height_px: r.height_px,
                })
                .collect();
            if pdf {
                let dest = out.unwrap_or_else(|| cfg.pdf_file.clone());
                let plan = forza_output::build_pdf_plan_ext(
                    &export_rows,
                    &cfg.gamertag,
                    &[],
                    &[],
                    forza_output::PdfRenderOptions {
                        show_dirty_symbol: cfg.pdf.show_dirty_lap_symbol,
                        dirty_symbol: cfg.pdf.dirty_lap_symbol.clone(),
                    },
                );
                let used_files = forza_output::render_pdf(&plan, &dest)
                    .map_err(|error| anyhow::anyhow!(error))?;
                println!(
                    "exported PDF with {} rows -> {} ({} source files)",
                    plan.stats.laps,
                    dest.display(),
                    used_files.len()
                );
            } else {
                let dest = out.unwrap_or_else(|| PathBuf::from("output/exports/results.csv"));
                let n = forza_output::csv::export_csv(&export_rows, &dest)?;
                println!("exported {n} rows -> {}", dest.display());
            }
            Ok(())
        }
        Command::ConfigCheck => cmd_config_check(&cli.config),
        Command::Maintenance(command) => match command {
            MaintenanceCommand::Status => cmd_db_status(&database_file(&cli.config)),
            MaintenanceCommand::Doctor { json } => cmd_db_doctor(&database_file(&cli.config), json),
            MaintenanceCommand::Upgrade => {
                let db_path = database_file(&cli.config);
                upgrade(&db_path)?;
                println!("db-upgrade: schema ready at {}", db_path.display());
                Ok(())
            }
            MaintenanceCommand::Reset { yes } => cmd_db_reset(&database_file(&cli.config), yes),
            MaintenanceCommand::Heal => cmd_db_heal(&database_file(&cli.config)),
        },
    }
}

/// Backfill the evidence chain on rows produced by builds that predate the
/// request_hash/runtime_snapshot_id/prompt_snapshot_id stamping. Only rows
/// failing the corresponding doctor checks are touched; values are derived
/// with the same canonical implementation the doctor recomputes with.
fn cmd_db_heal(db_path: &Path) -> anyhow::Result<()> {
    let conn = forza_db::open_connection(db_path)?;

    // 0. Recover runs left running by a crashed/closed process first: this
    //    cancels their pending results, heals missing results, and recomputes
    //    the stored counters (the healer's own backfills then run on stable
    //    rows).
    let reconciled = forza_db::repositories::reconcile_abandoned_runs(&conn).unwrap_or(0);

    // 0b. Recompute stored counters for every finished run (older builds
    //     wrote total_inputs into to_process; Python run_metrics derives all
    //     counters from relational rows).
    let counters_healed = conn.execute(
        "UPDATE extraction_runs SET
            total_inputs = (SELECT COUNT(*) FROM run_inputs WHERE run_id=extraction_runs.id),
            to_process = (SELECT COUNT(*) FROM run_inputs WHERE run_id=extraction_runs.id
                          AND decision='process'),
            skipped = (SELECT COUNT(*) FROM run_inputs WHERE run_id=extraction_runs.id
                       AND decision NOT IN ('process', 'duplicate')),
            duplicate_count = (SELECT COUNT(*) FROM run_inputs WHERE run_id=extraction_runs.id
                               AND decision='duplicate'),
            processed = (SELECT COUNT(*) FROM extraction_results WHERE run_id=extraction_runs.id),
            succeeded = (SELECT COUNT(*) FROM extraction_results WHERE run_id=extraction_runs.id
                         AND status='ok'),
            failed = (SELECT COUNT(*) FROM extraction_results WHERE run_id=extraction_runs.id
                      AND status='error'),
            review_case_count = (SELECT COUNT(*) FROM review_cases WHERE run_id=extraction_runs.id
                                 AND status='open')
         WHERE status != 'running'",
        [],
    )?;

    // 1. Results: retain the run's immutable prompt snapshot.
    let results_healed = conn.execute(
        "UPDATE extraction_results
         SET prompt_snapshot_id = (SELECT r.prompt_snapshot_id
                                   FROM extraction_runs r WHERE r.id = extraction_results.run_id)
         WHERE prompt_snapshot_id IS NULL
           AND run_id IN (SELECT id FROM extraction_runs WHERE prompt_snapshot_id IS NOT NULL)",
        [],
    )?;

    // 2. Attempts: identify the run's preflight runtime snapshot.
    let runtime_healed = conn.execute(
        "UPDATE extraction_attempts
         SET runtime_snapshot_id = (
             SELECT s.id FROM model_runtime_snapshots s
             WHERE s.run_id = extraction_attempts.run_id
               AND s.snapshot_kind = 'preflight'
             ORDER BY s.captured_at DESC LIMIT 1)
         WHERE runtime_snapshot_id IS NULL
           AND EXISTS (
               SELECT 1 FROM model_runtime_snapshots s
               WHERE s.run_id = extraction_attempts.run_id
                 AND s.snapshot_kind = 'preflight')",
        [],
    )?;

    // 3. Attempts: recompute the canonical request hash from exactly the
    //    persisted columns (the doctor's own recomputation).
    let mut stmt = conn.prepare(
        "SELECT a.id, a.request_messages_json, a.request_config_json,
                er.prompt_snapshot_id, a.model, im.file_hash,
                a.request_image_format, a.request_image_mime_type,
                a.request_image_width, a.request_image_height, a.request_image_bytes,
                a.request_hash
         FROM extraction_attempts a
         JOIN extraction_results er ON er.id = a.extraction_result_id
         JOIN image_files im ON im.id = a.image_file_id",
    )?;
    let rows = stmt.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, Option<String>>(1)?,
            row.get::<_, Option<String>>(2)?,
            row.get::<_, Option<String>>(3)?,
            row.get::<_, Option<String>>(4)?,
            row.get::<_, Option<String>>(5)?,
            row.get::<_, Option<String>>(6)?,
            row.get::<_, Option<String>>(7)?,
            row.get::<_, Option<i64>>(8)?,
            row.get::<_, Option<i64>>(9)?,
            row.get::<_, Option<i64>>(10)?,
            row.get::<_, Option<String>>(11)?,
        ))
    })?;

    let mut hashes_healed = 0usize;
    for row in rows {
        let (
            id,
            messages,
            config,
            prompt_id,
            model,
            source_hash,
            image_format,
            image_mime,
            width,
            height,
            bytes,
            stored_hash,
        ) = row?;
        let expected = forza_db::evidence::canonical_request_hash(
            messages.as_deref(),
            config.as_deref(),
            prompt_id.as_deref(),
            model.as_deref(),
            source_hash.as_deref(),
            image_format.as_deref(),
            image_mime.as_deref(),
            width,
            height,
            bytes,
        );
        if stored_hash.as_deref() != Some(expected.as_str()) {
            conn.execute(
                "UPDATE extraction_attempts SET request_hash=?2 WHERE id=?1",
                rusqlite::params![id, expected],
            )?;
            hashes_healed += 1;
        }
    }

    // 4. Images: backfill human-readable semantic names ("Track - Class.ext")
    //    for rows produced before the runner stamped them (readers prefer
    //    them over current_name; only NULL rows are touched).
    let candidates: Vec<(String, Option<String>, String)> = conn
        .prepare(
            "SELECT i.id, i.current_path, r.id
             FROM image_files i
             JOIN extraction_results r ON r.image_file_id = i.id
             WHERE i.semantic_name IS NULL AND r.status = 'ok'
             ORDER BY r.created_at DESC",
        )?
        .query_map([], |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)))?
        .collect::<Result<Vec<_>, _>>()?;
    let mut names_healed = 0usize;
    for (image_id, current_path, result_id) in &candidates {
        let Some(current_path) = current_path else {
            continue;
        };
        let before: Option<String> = conn.query_row(
            "SELECT semantic_name FROM image_files WHERE id = ?1",
            rusqlite::params![image_id],
            |r| r.get(0),
        )?;
        if before.is_some() {
            continue;
        }
        forza_app::services::extraction_runner::stamp_semantic_name(
            &conn,
            image_id,
            std::path::Path::new(current_path),
            result_id,
        );
        let after: Option<String> = conn.query_row(
            "SELECT semantic_name FROM image_files WHERE id = ?1",
            rusqlite::params![image_id],
            |r| r.get(0),
        )?;
        if after.is_some() {
            names_healed += 1;
        }
    }

    println!("db-heal: evidence backfill complete");
    println!("  abandoned runs reconciled  : {reconciled} run(s)");
    println!("  run counters recomputed    : {counters_healed} run(s)");
    println!("  results.prompt_snapshot_id : {results_healed} row(s)");
    println!("  attempts.runtime_snapshot  : {runtime_healed} row(s)");
    println!("  attempts.request_hash      : {hashes_healed} row(s)");
    println!("  images.semantic_name       : {names_healed} row(s)");
    println!("next step: run `forza rebuild` to refresh best-lap status and review cases");
    Ok(())
}
