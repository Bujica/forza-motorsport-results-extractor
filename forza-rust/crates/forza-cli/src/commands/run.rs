//! `run` command (plan + live extraction).

use std::path::Path;

use anyhow::Context;

use super::common::{load_validated_config, short_hash};

pub(crate) fn cmd_run(
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

    let conn = forza_db::open_connection(&cfg.database_file)
        .with_context(|| format!("open database {}", cfg.database_file.display()))?;

    // Single owner for discovery planning (see forza_app::build_discovery_plan):
    // retry/force/limit rules live there so CLI dry-run and the live runner
    // cannot diverge.
    let mut skipped_logs: Vec<String> = Vec::new();
    let discovery = forza_app::build_discovery_plan(
        forza_app::DiscoveryInput {
            conn: &conn,
            input_dir: &cfg.input_dir,
            force,
            retry_errors,
            limit,
            selected_image_file_ids: None,
        },
        &mut |line| skipped_logs.push(line),
    )
    .map_err(|e| anyhow::anyhow!("{e}"))?;
    for line in &skipped_logs {
        eprintln!("  {line}");
    }
    let plan = discovery.plan;
    let inventory_empty = discovery.inventory_empty;
    if retry_errors {
        println!("retry_errors = {} image(s) selected", plan.new_images.len());
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
                short_hash(&image.file_hash)
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
    })
    .map_err(|message| anyhow::anyhow!("{message}"))?;
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
