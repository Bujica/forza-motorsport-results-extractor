//! `forza` CLI — essential operational commands (migration plan §4.8).

use std::path::{Path, PathBuf};

use clap::{Parser, Subcommand};
use forza_db::doctor;
use forza_db::migration::{SchemaStatus, schema_status, upgrade};

#[derive(Parser)]
#[command(
    name = "forza",
    about = "Forza Motorsport Results Extractor (Rust line)"
)]
struct Cli {
    /// Path to the configuration file.
    #[arg(long, default_value = "forza_config.ini")]
    config: PathBuf,

    /// Subcommand to run.
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Launch the graphical interface.
    Gui,
    /// Process screenshots (only `--dry-run` planning is implemented).
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
    Rebuild,
    /// Export the clean best-lap table to CSV (PDF renderer lands with F10).
    Export {
        /// Destination CSV path.
        #[arg(long)]
        out: Option<PathBuf>,
    },
    /// Validate the configuration file and print a report.
    ConfigCheck,
    /// Database maintenance operations.
    Maintenance {
        #[command(subcommand)]
        command: MaintenanceCommand,
    },
}

#[derive(Subcommand)]
enum MaintenanceCommand {
    /// Show the schema state of the runtime database.
    #[command(name = "db-status")]
    Status,
    /// Run the basic DB doctor battery.
    #[command(name = "db-doctor")]
    Doctor {
        /// Emit the report as JSON.
        #[arg(long)]
        json: bool,
    },
    /// Create the schema on an empty database (refuses foreign versions).
    #[command(name = "db-upgrade")]
    Upgrade,
    /// Delete the database files after warning about WAL/SHM sidecars.
    #[command(name = "db-reset")]
    Reset {
        /// Skip the confirmation prompt.
        #[arg(long)]
        yes: bool,
    },
}

fn database_file(config_path: &Path) -> PathBuf {
    match forza_config::load_config(config_path, false) {
        Ok((cfg, _)) => cfg.database_file,
        Err(_) => PathBuf::from("data/forza.sqlite3"),
    }
}

fn cmd_config_check(config_path: &Path) -> anyhow::Result<()> {
    let (cfg, warnings) = forza_config::load_config(config_path, false)?;
    for warning in &warnings {
        println!("warning: {warning}");
    }
    match forza_config::validate_config(&cfg) {
        Ok(()) => {
            println!("config-check: OK");
            println!("  database_file = {}", cfg.database_file.display());
            println!("  input_dir     = {}", cfg.input_dir.display());
            Ok(())
        }
        Err(errors) => {
            eprintln!("config-check failed:");
            for error in errors {
                eprintln!("  - {error}");
            }
            std::process::exit(1);
        }
    }
}

fn cmd_db_status(db_path: &Path) -> anyhow::Result<()> {
    let status = schema_status(db_path)?;
    let label = match status {
        SchemaStatus::Empty => "empty",
        SchemaStatus::Current => "current",
        SchemaStatus::Incompatible { .. } => "incompatible",
    };
    let extra = match status {
        SchemaStatus::Incompatible { found } => format!(" (user_version={found})"),
        _ => String::new(),
    };
    println!("database_file = {}", db_path.display());
    println!("schema_state  = {label}{extra}");
    if status != SchemaStatus::Current {
        std::process::exit(1);
    }
    Ok(())
}

fn cmd_db_doctor(db_path: &Path, json: bool) -> anyhow::Result<()> {
    let report = doctor::doctor_on_path(db_path)?;
    if json {
        println!(
            "{{\"ok\": {}, \"schema_status\": \"{}\", \"user_version\": {}, \"checks\": [{}]}}",
            report.ok,
            report.schema_status,
            report.user_version,
            report
                .checks
                .iter()
                .map(|c| {
                    format!(
                        "{{\"key\": \"{}\", \"ok\": {}, \"detail\": \"{}\"}}",
                        c.key,
                        c.ok,
                        c.detail.replace('"', "'")
                    )
                })
                .collect::<Vec<_>>()
                .join(", ")
        );
    } else {
        println!("database_file = {}", db_path.display());
        println!(
            "schema_state  = {} (user_version={})",
            report.schema_status, report.user_version
        );
        for check in &report.checks {
            println!(
                "  [{}] {} — {}",
                if check.ok { "OK" } else { "FAIL" },
                check.key,
                check.detail
            );
        }
        println!("ok = {}", report.ok);
    }
    if !report.ok {
        std::process::exit(1);
    }
    Ok(())
}

fn cmd_db_reset(db_path: &Path, yes: bool) -> anyhow::Result<()> {
    let sidecars = [
        PathBuf::from(format!("{}-wal", db_path.display())),
        PathBuf::from(format!("{}-shm", db_path.display())),
    ];
    println!("This deletes:");
    for path in std::iter::once(db_path.to_path_buf()).chain(sidecars.iter().cloned()) {
        if path.exists() {
            println!("  {}", path.display());
        }
    }
    if !yes {
        println!("Re-run with --yes to confirm.");
        return Ok(());
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
    dry_run: bool,
    force: bool,
    retry_errors: bool,
    limit: Option<usize>,
) -> anyhow::Result<()> {
    let (cfg, warnings) = forza_config::load_config(config_path, false)?;
    for warning in &warnings {
        eprintln!("warning: {warning}");
    }
    if force && retry_errors {
        return Err(anyhow::anyhow!(
            "--force and --retry-errors cannot be combined."
        ));
    }
    if !dry_run && !force && !retry_errors {
        return Err(anyhow::anyhow!(
            "full runs (LM Studio extraction) are not implemented yet; use --dry-run"
        ));
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
                new_images.push(forza_pipeline::planning::DiscoveredImage {
                    path: candidate,
                    file_hash: hash,
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

fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Command::Gui => forza_gui::run(&cli.config),
        Command::Rebuild => {
            let (cfg, _) = forza_config::load_config(&cli.config, false)?;
            let conn = forza_db::open_connection(&cfg.database_file)?;
            let outcome = forza_app::services::rebuild::rebuild(&conn, &cfg.gamertag)
                .map_err(|e| anyhow::anyhow!(e))?;
            println!(
                "rebuild: {} best-lap winner(s); reviews +{} kept {} auto-resolved {}",
                outcome.best_lap_winners,
                outcome.review_inserted,
                outcome.review_kept,
                outcome.review_auto_resolved
            );
            Ok(())
        }
        Command::Run {
            dry_run,
            force,
            retry_errors,
            limit,
        } => cmd_run(&cli.config, dry_run, force, retry_errors, limit),
        Command::Export { out } => {
            let (cfg, _) = forza_config::load_config(&cli.config, false)?;
            let conn = forza_db::open_connection(&cfg.database_file)?;
            let rows =
                forza_db::repositories::laps::list_clean_flat(&conn, &cfg.gamertag.to_lowercase())?;
            if rows.is_empty() {
                println!("export: no best-lap rows to export");
                return Ok(());
            }
            let dest = out.unwrap_or_else(|| PathBuf::from("output/exports/results.csv"));
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
            let n = forza_output::csv::export_csv(&export_rows, &dest)?;
            println!("exported {n} rows -> {}", dest.display());
            Ok(())
        }
        Command::ConfigCheck => cmd_config_check(&cli.config),
        Command::Maintenance { command } => match command {
            MaintenanceCommand::Status => cmd_db_status(&database_file(&cli.config)),
            MaintenanceCommand::Doctor { json } => cmd_db_doctor(&database_file(&cli.config), json),
            MaintenanceCommand::Upgrade => {
                let db_path = database_file(&cli.config);
                upgrade(&db_path)?;
                println!("db-upgrade: schema ready at {}", db_path.display());
                Ok(())
            }
            MaintenanceCommand::Reset { yes } => cmd_db_reset(&database_file(&cli.config), yes),
        },
    }
}
