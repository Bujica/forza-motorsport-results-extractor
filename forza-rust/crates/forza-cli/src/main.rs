//! `forza` CLI — essential operational commands (migration plan §4.8).

use std::path::PathBuf;

use clap::{Parser, Subcommand};
use forza_db::migration::upgrade;

/// Build identity shared with the GUI and stamped into every run row.
const APP_VERSION: &str = forza_app::APP_VERSION;

mod commands;

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
    /// Launch the graphical interface (Slint desktop app).
    ///
    /// Same entry point as the `forza-gui` binary (`forza_gui::run`); the
    /// CLI depends on `forza-gui` only for this subcommand.
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
fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();
    let strict = cli.strict;
    match cli.command {
        Command::Gui => forza_gui::run(&cli.config),
        Command::Rebuild => commands::rebuild::cmd_rebuild(&cli.config, strict),
        Command::Run {
            dry_run,
            force,
            retry_errors,
            limit,
        } => commands::run::cmd_run(&cli.config, strict, dry_run, force, retry_errors, limit),
        Command::Export { out, pdf } => commands::export::cmd_export(&cli.config, strict, out, pdf),
        Command::ConfigCheck => commands::config::cmd_config_check(&cli.config),
        Command::Maintenance(command) => {
            use commands::common::database_file;
            match command {
                MaintenanceCommand::Status => {
                    commands::maintenance::cmd_db_status(&database_file(&cli.config))
                }
                MaintenanceCommand::Doctor { json } => {
                    commands::maintenance::cmd_db_doctor(&database_file(&cli.config), json)
                }
                MaintenanceCommand::Upgrade => {
                    let db_path = database_file(&cli.config);
                    upgrade(&db_path)?;
                    println!("db-upgrade: schema ready at {}", db_path.display());
                    Ok(())
                }
                MaintenanceCommand::Reset { yes } => {
                    commands::maintenance::cmd_db_reset(&database_file(&cli.config), yes)
                }
                MaintenanceCommand::Heal => {
                    commands::heal::cmd_db_heal(&cli.config, &database_file(&cli.config))
                }
            }
        }
    }
}
