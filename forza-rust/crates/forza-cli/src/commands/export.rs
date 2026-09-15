//! `export` command (CSV or PDF report).

use std::path::{Path, PathBuf};

use anyhow::Context;

use super::common::load_validated_config;

pub(crate) fn cmd_export(
    config_path: &Path,
    strict: bool,
    out: Option<PathBuf>,
    pdf: bool,
) -> anyhow::Result<()> {
    let cfg = load_validated_config(config_path, strict)?;
    let conn = forza_db::open_connection(&cfg.database_file)
        .with_context(|| format!("open database {}", cfg.database_file.display()))?;
    let rows = forza_db::repositories::laps::list_clean_flat(&conn, &cfg.gamertag.to_lowercase())?;
    if rows.is_empty() {
        println!("export: no best-lap rows to export");
        return Ok(());
    }
    let export_rows = forza_app::flat_to_export_rows(&rows);
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
        let used_files =
            forza_output::render_pdf(&plan, &dest).map_err(|error| anyhow::anyhow!(error))?;
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
