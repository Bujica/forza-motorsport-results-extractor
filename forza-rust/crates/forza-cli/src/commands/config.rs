//! `config-check` command.

use std::path::Path;

pub(crate) fn cmd_config_check(config_path: &Path) -> anyhow::Result<()> {
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
