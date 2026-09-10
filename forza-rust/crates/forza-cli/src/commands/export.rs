//! `export` command (CSV or PDF report).

use std::path::{Path, PathBuf};

use super::common::load_validated_config;

pub(crate) fn cmd_export(
    config_path: &Path,
    strict: bool,
    out: Option<PathBuf>,
    pdf: bool,
) -> anyhow::Result<()> {
    let cfg = load_validated_config(config_path, strict)?;
    let conn = forza_db::open_connection(&cfg.database_file)?;
    let rows = forza_db::repositories::laps::list_clean_flat(&conn, &cfg.gamertag.to_lowercase())?;
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
