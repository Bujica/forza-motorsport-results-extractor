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

fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();
    match cli.command {
        Command::Gui => forza_gui::run(&cli.config),
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
