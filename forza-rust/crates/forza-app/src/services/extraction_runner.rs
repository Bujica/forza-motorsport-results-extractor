//! Live extraction runner: full pipeline on a dedicated thread with
//! cooperative cancellation — discovery → plan → encode → LM Studio →
//! persist attempts/result/laps → run counters. Emits typed events for the
//! GUI (progress, per-image outcomes, log lines).

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::mpsc::channel;
use std::time::Instant;

use rusqlite::Connection;
use rusqlite::OptionalExtension;

/// Owned image data for worker threads (avoids borrowing `plan` across threads).
///
/// `result_id`/`input_id`/`input_order` are pre-allocated on the main thread:
/// per-worker `done+1` counters are NOT unique per run, so workers must never
/// compute `input_order` themselves nor stamp metadata with
/// `WHERE run_id AND input_order` (that overwrites other workers' rows).
#[derive(Debug, Clone)]
struct WorkerImage {
    path: PathBuf,
    file_hash: String,
    result_id: String,
    input_id: i64,
    input_order: i64,
}

use crate::services::run_control::RunControl;
use forza_config::AppConfig;
use forza_db::repositories::runs::{
    RunInputOnly, RunInsert, RunMetadata, RuntimeSnapshotInsert, complete_run,
    find_image_id_by_hash, insert_processed_input_full, insert_prompt_snapshot, insert_run,
    insert_run_input_full, insert_run_input_only, insert_runtime_snapshot,
    link_run_prompt_snapshot, mark_run_running, reconcile_abandoned_runs, update_run_metadata,
};
use forza_db::repositories::{known_hashes, known_path_hashes, list_failed_images_for_retry};
use forza_lmstudio::backend::{BackendConfig, LMStudioBackend};
use forza_lmstudio::load_config::DesiredLoadConfig;
use forza_lmstudio::prompts;
use forza_lmstudio::protocol::ModelAttemptRecord;
use forza_pipeline::planning::KnownPathHashes;
use forza_pipeline::{encode_image_payload, find_images, plan_images};

/// Events streamed back to the UI thread (plain data — widget-free).
#[derive(Debug, Clone)]
pub enum RunEvent {
    Started {
        run_id: String,
        total: usize,
    },
    Plan {
        new: usize,
        cached: usize,
        batch: usize,
        existing: usize,
        skipped: usize,
    },
    ImageStarted {
        name: String,
    },
    ImageDone {
        name: String,
        ok: bool,
        laps: usize,
    },
    Progress {
        done: usize,
        total: usize,
    },
    Log(String),
    Finished {
        cancelled: bool,
        processed: usize,
        succeeded: usize,
        failed: usize,
        elapsed_s: f64,
    },
    Failed(String),
}

/// Everything the runner needs, built from the loaded AppConfig.
#[derive(Debug, Clone)]
pub struct RunParams {
    pub database_file: PathBuf,
    pub input_dir: PathBuf,
    pub gamertag: String,
    pub force: bool,
    /// Retry only images whose latest extraction result is `error`.
    /// Mutually exclusive with `force` (Python run contract).
    pub retry_errors: bool,
    /// When present, process only these image-file IDs from the inventory.
    pub selected_image_file_ids: Option<Vec<String>>,
    /// Optional CLI cap for the number of images sent to extraction.
    pub max_images: Option<usize>,
    /// Number of parallel extraction workers (1 = sequential).
    pub workers: u32,
    // LLM
    pub url: String,
    pub model: String,
    pub max_tokens: i64,
    pub temperature: f64,
    pub timeout_connect: u64,
    pub timeout_read: u64,
    pub max_retries: u32,
    pub prompt_id: String,
    pub context_length: i64,
    pub reasoning_mode: Option<String>,
    pub eval_batch_size: Option<i64>,
    pub physical_batch_size: Option<i64>,
    pub flash_attention: bool,
    pub offload_kv_cache_to_gpu: bool,
    pub temp_min_f: f64,
    pub temp_max_f: f64,
    /// Debug verbosity (Python per-run `debug` parity): extra per-image
    /// diagnostic lines in the run log (hashes, ids, attempt counts).
    pub verbose: bool,
    // image pipeline
    pub max_width: u32,
    pub encode_quality: u8,
    pub image_format: String,
    pub grayscale: bool,
    /// Build identity of the calling binary, persisted on the run row.
    pub app_version: String,
}

impl RunParams {
    pub fn from_config(cfg: &AppConfig, force: bool) -> Self {
        Self {
            database_file: cfg.database_file.clone(),
            input_dir: cfg.input_dir.clone(),
            gamertag: cfg.gamertag.clone(),
            force,
            app_version: crate::APP_VERSION.to_string(),
            retry_errors: false,
            selected_image_file_ids: None,
            max_images: None,
            workers: cfg.workers as u32,
            url: cfg.llm.url.clone(),
            model: cfg.llm.model.clone(),
            max_tokens: cfg.llm.max_completion_tokens,
            temperature: cfg.llm.temperature,
            timeout_connect: cfg.llm.timeout_connect.max(1) as u64,
            timeout_read: cfg.llm.timeout_read.max(1) as u64,
            max_retries: cfg.llm.max_retries.max(1) as u32,
            prompt_id: cfg.prompt.active.clone(),
            context_length: cfg.llm.context_length.unwrap_or(5000),
            reasoning_mode: cfg.llm.reasoning_mode.clone(),
            eval_batch_size: cfg.llm.eval_batch_size,
            physical_batch_size: cfg.llm.physical_batch_size,
            flash_attention: cfg.llm.flash_attention,
            offload_kv_cache_to_gpu: cfg.llm.offload_kv_cache_to_gpu,
            temp_min_f: cfg.validation.temp_min_f,
            temp_max_f: cfg.validation.temp_max_f,
            verbose: false,
            max_width: cfg.image.max_width.clamp(1, u32::MAX as i64) as u32,
            encode_quality: cfg.image.encode_quality.clamp(1, 100) as u8,
            image_format: cfg.llm.image_format.clone(),
            grayscale: cfg.image.grayscale,
        }
    }

    fn desired_load_config(&self) -> DesiredLoadConfig {
        DesiredLoadConfig {
            context_length: self.context_length,
            eval_batch_size: self.eval_batch_size,
            physical_batch_size: self.physical_batch_size,
            flash_attention: self.flash_attention,
            offload_kv_cache_to_gpu: self.offload_kv_cache_to_gpu,
        }
    }

    fn backend_config(&self) -> BackendConfig {
        BackendConfig {
            url: self.url.clone(),
            model: self.model.clone(),
            max_tokens: self.max_tokens,
            temperature: self.temperature,
            timeout_connect_secs: self.timeout_connect,
            timeout_read_secs: self.timeout_read,
            max_retries: self.max_retries,
            system_prompt: prompts::get_system_prompt(&self.prompt_id)
                .unwrap_or_default()
                .to_string(),
            context_length: self.context_length,
            reasoning_mode: self.reasoning_mode.clone(),
        }
    }
}

fn now_run_id() -> String {
    // Timestamp-prefixed like the Python run ids (YYYYMMDD_HHMMSS_xxxx):
    // lexicographic order equals chronological order (frontier relies on it).
    // Sub-second + pid suffix: two runs started within the same second must
    // not collide on the run-id PK (bare `{ts}_rust` did).
    let now = chrono_like_now();
    let subsec = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.subsec_micros())
        .unwrap_or(0);
    format!("{now}_{subsec:06}_{}_rust", std::process::id())
}

fn chrono_like_now() -> String {
    // Local time is fine for id uniqueness; format YYYYMMDD_HHMMSS.
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs() as i64;
    let days = secs / 86_400;
    let rem = secs % 86_400;
    let (h, m, s) = (rem / 3600, (rem % 3600) / 60, rem % 60);
    // Civil-from-days algorithm (Howard Hinnant) for Y/M/D.
    let z = days + 719_468;
    let era = z / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let mth = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if mth <= 2 { y + 1 } else { y };
    format!("{y:04}{mth:02}{d:02}_{h:02}{m:02}{s:02}")
}

fn upsert_image_for_run(
    conn: &Connection,
    path: &std::path::Path,
    file_hash: &str,
) -> Result<(String, Option<(i64, i64)>), String> {
    if let Some(existing) = find_image_id_by_hash(conn, file_hash).map_err(|e| e.to_string())? {
        // Refresh current path/name so the inventory reflects reality.
        let name = path
            .file_name()
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_default();
        conn.execute(
            "UPDATE image_files SET current_path=?2, current_name=?3 WHERE id=?1",
            rusqlite::params![existing, path.to_string_lossy(), name],
        )
        .map_err(|e| e.to_string())?;
        let dims = conn
            .query_row(
                "SELECT width_px, height_px FROM image_files WHERE id=?1",
                rusqlite::params![existing],
                |r| {
                    Ok((
                        r.get::<_, Option<i64>>(0)?.unwrap_or(0),
                        r.get::<_, Option<i64>>(1)?.unwrap_or(0),
                    ))
                },
            )
            .map_err(|e| e.to_string())?;
        return Ok((existing, Some(dims)));
    }

    // A stale non-available row with the same hash (e.g. retired by a
    // path-conflict) still owns the deterministic `img-{hash}` PK:
    // reactivate it instead of INSERT-colliding and aborting the whole run.
    let id = format!("img-{file_hash}");
    let stale: Option<String> = conn
        .query_row(
            "SELECT id FROM image_files WHERE id = ?1 LIMIT 1",
            rusqlite::params![id],
            |r| r.get(0),
        )
        .optional()
        .map_err(|e| e.to_string())?;
    if let Some(stale_id) = stale {
        let name0 = path
            .file_name()
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_default();
        conn.execute(
            "UPDATE image_files SET current_path=?2, current_name=?3, file_status='available',
                    missing_at=NULL, last_seen_at=datetime('now'), updated_at=datetime('now')
              WHERE id=?1",
            rusqlite::params![stale_id, path.to_string_lossy(), name0],
        )
        .map_err(|e| e.to_string())?;
        let dims = conn
            .query_row(
                "SELECT width_px, height_px FROM image_files WHERE id=?1",
                rusqlite::params![stale_id],
                |r| {
                    Ok((
                        r.get::<_, Option<i64>>(0)?.unwrap_or(0),
                        r.get::<_, Option<i64>>(1)?.unwrap_or(0),
                    ))
                },
            )
            .map_err(|e| e.to_string())?;
        return Ok((stale_id, Some(dims)));
    }

    let meta = forza_pipeline::inspect_metadata(path).ok();
    let name = path
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_default();
    // A different file arriving at an existing path retires the previous
    // available owner first (Python upsert path-conflict handling), so two
    // available rows never share one current_path.
    conn.execute(
        "UPDATE image_files
         SET file_status='missing', missing_at=datetime('now'), updated_at=datetime('now')
         WHERE current_path=?1 AND file_hash!=?2 AND file_status='available'",
        rusqlite::params![path.to_string_lossy(), file_hash],
    )
    .map_err(|e| e.to_string())?;
    conn.execute(
        "INSERT INTO image_files
            (id, file_hash, current_name, current_path, size_bytes,
             width_px, height_px, image_format, mime_type,
             bit_depth, color_mode, image_metadata_json,
             file_modified_at, race_datetime, race_date, race_datetime_source,
             file_status, best_lap_status, first_seen_at, last_seen_at,
             created_at, updated_at)
         VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,
                 'available','pending',
                 datetime('now'),datetime('now'),datetime('now'),datetime('now'))",
        rusqlite::params![
            id,
            file_hash,
            name,
            path.to_string_lossy(),
            std::fs::metadata(path).map(|m| m.len() as i64).unwrap_or(0),
            meta.as_ref().map(|m| m.width_px as i64).unwrap_or(0),
            meta.as_ref().map(|m| m.height_px as i64).unwrap_or(0),
            meta.as_ref()
                .map(|m| m.image_format.to_lowercase())
                .unwrap_or_else(|| "png".into()),
            meta.as_ref()
                .and_then(|m| m.mime_type.clone())
                .unwrap_or_else(|| "image/png".into()),
            meta.as_ref().and_then(|m| m.bit_depth.map(|b| b as i64)),
            meta.as_ref().map(|m| m.color_mode.clone()),
            meta.as_ref().map(|m| m.image_metadata_json.clone()),
            meta.as_ref().and_then(|m| m.file_modified_at.clone()),
            meta.as_ref().and_then(|m| m.race_datetime.clone()),
            meta.as_ref().and_then(|m| m.race_date.clone()),
            meta.as_ref()
                .map(|m| m.race_datetime_source.clone())
                .unwrap_or_else(|| "file_modified_at".into()),
        ],
    )
    .map_err(|e| e.to_string())?;
    Ok((id, None))
}

/// Spawn the extraction run on a dedicated thread. `control` is honoured
/// cooperatively at safe checkpoints (between images); the current image
/// finishes first. When `params.workers > 1` images are processed in
/// parallel across that many Tokio worker tasks.
pub fn spawn_extraction<F>(
    params: RunParams,
    control: RunControl,
    on_event: F,
) -> std::thread::JoinHandle<()>
where
    F: Fn(RunEvent) + Send + 'static,
{
    std::thread::Builder::new()
        .name("forza-extraction".into())
        .spawn(move || run_blocking(params, control, on_event))
        .unwrap_or_else(|e| panic!("extraction thread: {e}"))
}

fn run_blocking<F>(params: RunParams, control: RunControl, on_event: F)
where
    F: Fn(RunEvent),
{
    let started = Instant::now();
    let runtime = match tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(rt) => rt,
        Err(e) => {
            on_event(RunEvent::Failed(format!("tokio runtime: {e}")));
            return;
        }
    };

    let outcome: Result<(usize, usize, usize, usize, usize), String> =
        runtime.block_on(async { run_async(&params, &control, &on_event).await });

    match outcome {
        Ok((processed, succeeded, failed, skipped, dupes)) => {
            on_event(RunEvent::Finished {
                cancelled: control.is_cancelled(),
                processed,
                succeeded,
                failed,
                elapsed_s: started.elapsed().as_secs_f64(),
            });
            let _ = (skipped, dupes);
        }
        Err(message) => on_event(RunEvent::Failed(message)),
    }
}

async fn run_async<F>(
    params: &RunParams,
    control: &RunControl,
    on_event: &F,
) -> Result<(usize, usize, usize, usize, usize), String>
where
    F: Fn(RunEvent),
{
    if params.force && params.retry_errors {
        return Err("--force and --retry-errors cannot be combined.".into());
    }
    let conn = forza_db::open_connection(&params.database_file).map_err(|e| e.to_string())?;

    // ── Abandoned run reconciliation ──────────────────────────────────────
    let abandoned = reconcile_abandoned_runs(&conn).map_err(|e| e.to_string())?;
    if abandoned > 0 {
        on_event(RunEvent::Log(format!(
            "reconciled {abandoned} abandoned run(s)"
        )));
    }

    // ── Discovery + plan ─────────────────────────────────────────────────
    // Retry mode replaces discovery: only images whose latest result is
    // still `error` are selected (Python `_retry_error_discovery`).
    let mut plan = if params.retry_errors {
        let failed = list_failed_images_for_retry(&conn).map_err(|e| e.to_string())?;
        let mut new_images = Vec::new();
        let mut missing = 0usize;
        for (path, hash) in failed {
            let candidate = PathBuf::from(&path);
            if candidate.exists() {
                // Re-hash the live file: the stored hash may be stale (bytes
                // changed after the failed run) and upsert/insert by a stale
                // hash mislinks the image.
                let live_hash = forza_pipeline::file_hash(&candidate).unwrap_or(hash);
                new_images.push(forza_pipeline::planning::DiscoveredImage {
                    path: candidate,
                    file_hash: live_hash,
                });
            } else {
                missing += 1;
            }
        }
        if new_images.is_empty() {
            on_event(RunEvent::Log("No failed images to retry.".into()));
        } else {
            on_event(RunEvent::Log(format!(
                "retry: {} failed image(s) selected{}",
                new_images.len(),
                if missing > 0 {
                    format!(" ({missing} missing on disk ignored)")
                } else {
                    String::new()
                }
            )));
        }
        let total = new_images.len();
        forza_pipeline::planning::ImageDiscoveryPlan {
            total,
            new_images,
            duplicates: Vec::new(),
            existing_images: Vec::new(),
            skipped_images: Vec::new(),
        }
    } else {
        let mut images = find_images(&params.input_dir);
        if let Some(selected_ids) = &params.selected_image_file_ids {
            let selected_paths = selected_image_paths(&conn, selected_ids)?;
            images.retain(|image| selected_paths.contains(&path_key(image)));
            on_event(RunEvent::Log(format!(
                "selected run: {} image(s) from Images",
                images.len()
            )));
        }
        if images.is_empty() {
            on_event(RunEvent::Log("no supported images in input folder".into()));
        }
        let known_paths: KnownPathHashes = known_path_hashes(&conn).map_err(|e| e.to_string())?;
        let known_set = known_hashes(&conn).map_err(|e| e.to_string())?;
        let plan = plan_images(&images, &known_set, &known_paths, params.force)
            .map_err(|e| e.to_string())?;
        // Python's inventory register step logs every duplicate skip in place.
        let _skipped_duplicates = forza_pipeline::log_duplicate_skips(&plan);
        plan
    };

    if let Some(max_images) = params.max_images {
        plan.new_images.truncate(max_images);
        // The run-start event describes the work this invocation can actually
        // perform, not the number of files discovered before applying the CLI
        // cap. Keep the full discovery count in the plan only when no cap was
        // requested.
        plan.total = plan.new_images.len();
    }

    let cached = plan
        .duplicates
        .iter()
        .filter(|d| d.reason == "cached")
        .count();
    let batch = plan
        .duplicates
        .iter()
        .filter(|d| d.reason == "batch")
        .count();
    on_event(RunEvent::Plan {
        new: plan.process_count(),
        cached,
        batch,
        existing: plan.existing_images.len(),
        skipped: plan.skipped_images.len(),
    });

    // ── Run row ──────────────────────────────────────────────────────────
    // ── Run row ──────────────────────────────────────────────────────────
    // Phase checkpoint (Python honours pause/cancel between phases too):
    // blocks while paused, before any run evidence or events are produced.
    if !control.checkpoint() {
        on_event(RunEvent::Log(
            "cancellation requested — stopping before extraction".into(),
        ));
        // Actually stop: falling through would create the run row, prompt
        // snapshot and Started event despite the log claiming otherwise.
        return Ok((0, 0, 0, 0, 0));
    }
    let run_id = now_run_id();
    insert_run(
        &conn,
        &RunInsert {
            id: run_id.clone(),
            status: "pending".into(),
            mode: "normal".into(),
        },
    )
    .map_err(|e| e.to_string())?;
    let input_dir = params.input_dir.to_string_lossy().into_owned();
    let system_prompt = prompts::get_system_prompt(&params.prompt_id).unwrap_or_default();
    let prompt_hash = prompts::payload_hash(system_prompt);
    let prompt_snapshot_id = prompts::snapshot_id(&params.prompt_id);
    insert_prompt_snapshot(
        &conn,
        &prompt_snapshot_id,
        &params.prompt_id,
        &prompt_hash,
        system_prompt,
    )
    .map_err(|e| e.to_string())?;
    link_run_prompt_snapshot(&conn, &run_id, &prompt_snapshot_id, &prompt_hash)
        .map_err(|e| e.to_string())?;
    update_run_metadata(
        &conn,
        &run_id,
        &RunMetadata {
            backend: "lmstudio",
            model: &params.model,
            input_dir: &input_dir,
            prompt_name: &params.prompt_id,
            prompt_hash: Some(&prompt_hash),
            workers: i64::from(params.workers),
            image_format: &params.image_format,
            max_width: i64::from(params.max_width),
            encode_quality: i64::from(params.encode_quality),
            grayscale: params.grayscale,
            context_length: params.context_length,
            reasoning_mode: params.reasoning_mode.as_deref(),
            max_completion_tokens: params.max_tokens,
            temperature: params.temperature,
            max_retries: i64::from(params.max_retries),
            timeout_connect: params.timeout_connect as i64,
            timeout_read: params.timeout_read as i64,
            config_extra_json: Some(&params.app_version),
        },
    )
    .map_err(|e| e.to_string())?;
    mark_run_running(&conn, &run_id).map_err(|e| e.to_string())?;
    on_event(RunEvent::Started {
        run_id: run_id.clone(),
        total: plan.total,
    });

    let mut input_order = 0i64;
    let _processed = 0usize;
    let _succeeded = 0usize;
    let _failed = 0usize;

    // Inventory decisions for everything the run considered.
    for existing in &plan.existing_images {
        input_order += 1;
        let image_id = find_image_id_by_hash(&conn, &existing.file_hash)
            .map_err(|e| e.to_string())?
            .unwrap_or_default();
        insert_run_input_only(
            &conn,
            &run_id,
            Some(&image_id),
            "skip",
            input_order,
            &existing.path.to_string_lossy(),
        )
        .map_err(|e| e.to_string())?;
    }
    // Batch-duplicate linkage: the doctor requires `duplicate_of_input_id`
    // for `batch` duplicates pointing at the earlier same-run input row.
    use std::collections::HashMap as _DupMap;
    let mut canonical_input: _DupMap<String, i64> = _DupMap::new();
    for dup in &plan.duplicates {
        input_order += 1;
        let kind = if dup.reason == "batch" {
            "batch"
        } else {
            "hash"
        };
        let hash = dup
            .duplicate_of_hash
            .clone()
            .unwrap_or_else(|| dup.file_hash.clone());
        // For batch duplicates the canonical input was already recorded in
        // this run (first occurrence wins in planning order); for hash
        // duplicates there is no same-run canonical row.
        let duplicate_of_input_id: Option<i64> = if kind == "batch" {
            canonical_input.get(&hash).copied()
        } else {
            None
        };
        // Record the canonical hash itself so later batch rows can link.
        // (The canonical *image* row keeps its own process/skip input.)
        insert_run_input_full(
            &conn,
            &run_id,
            &RunInputOnly {
                image_file_id: None,
                decision: "duplicate",
                input_order,
                input_path: &dup.path.to_string_lossy(),
                file_hash: Some(&dup.file_hash),
                duplicate_kind: Some(kind),
                duplicate_of_hash: Some(&hash),
                duplicate_of_input_id,
            },
        )
        .map_err(|e| e.to_string())
        .map(|id| {
            canonical_input.entry(hash.clone()).or_insert(id);
            id
        })?;
    }
    for skipped in &plan.skipped_images {
        input_order += 1;
        insert_run_input_only(
            &conn,
            &run_id,
            None,
            "hash_failed",
            input_order,
            &skipped.path.to_string_lossy(),
        )
        .map_err(|e| e.to_string())?;
    }

    let total_new = plan.new_images.len();
    let process_reason = if params.retry_errors {
        "retry_errors"
    } else if params.force {
        "force"
    } else {
        "full_run"
    };

    let (processed, succeeded, failed) = if params.workers > 1 && total_new > 0 {
        // ── Multi-worker parallel extraction ────────────────────────────
        let workers = params.workers as usize;
        let (event_tx, event_rx) = channel();
        let control = Arc::new(control.clone());

        // Pre-allocate ALL inputs/results/metadata on the main connection:
        // per-worker `done+1` counters are not unique per run, and concurrent
        // `MAX(id)+1` inserts race — so workers never insert inputs, they only
        // process pre-created (result_id, input_id) pairs.
        let mut ready: Vec<WorkerImage> = Vec::with_capacity(total_new);
        let mut pre_failed = 0usize;
        for image in &plan.new_images {
            input_order += 1;
            let name = image
                .path
                .file_name()
                .map(|n| n.to_string_lossy().to_string())
                .unwrap_or_default();
            let (image_file_id, _) =
                match upsert_image_for_run(&conn, &image.path, &image.file_hash) {
                    Ok(v) => v,
                    Err(e) => {
                        let _ = event_tx.send(RunEvent::ImageDone {
                            name,
                            ok: false,
                            laps: 0,
                        });
                        let _ = event_tx.send(RunEvent::Log(format!("upsert: {e}")));
                        pre_failed += 1;
                        continue;
                    }
                };
            let (result_id, input_id) = match insert_processed_input_full(
                &conn,
                &run_id,
                &image_file_id,
                &image.path.to_string_lossy(),
                process_reason,
                input_order,
            ) {
                Ok(v) => v,
                Err(e) => {
                    let _ = event_tx.send(RunEvent::ImageDone {
                        name,
                        ok: false,
                        laps: 0,
                    });
                    let _ = event_tx.send(RunEvent::Log(format!("insert result: {e}")));
                    pre_failed += 1;
                    continue;
                }
            };
            stamp_result_prompt(&conn, &result_id, &prompt_snapshot_id);
            stamp_input_metadata(
                &conn,
                &run_id,
                input_id,
                &image.file_hash,
                &name,
                &image.path,
            );
            // Link batch duplicates to their canonical same-run input.
            canonical_input
                .entry(image.file_hash.clone())
                .or_insert(input_id);
            ready.push(WorkerImage {
                path: image.path.clone(),
                file_hash: image.file_hash.clone(),
                result_id,
                input_id,
                input_order,
            });
        }

        // Split images into worker batches (round-robin for fairness).
        let mut batches: Vec<Vec<WorkerImage>> = vec![Vec::new(); workers];
        for (idx, item) in ready.into_iter().enumerate() {
            batches[idx % workers].push(item);
        }

        // Spawn preflight snapshot on the main connection (single call).
        let snapshot = {
            let backend = LMStudioBackend::new(params.backend_config(), Default::default())
                .map_err(|e| fail_run_preflight(&conn, &run_id, &e.to_string()))?;
            let desired = params.desired_load_config();
            backend
                .preflight_snapshot(&desired)
                .await
                .map_err(|_| {
                    fail_run_preflight(
                        &conn,
                        &run_id,
                        "LM Studio is not reachable — start LM Studio (with the server on) and try again",
                    )
                })?
        };
        let snapshot_id = format!("runtime-{run_id}-preflight");
        let insert = RuntimeSnapshotInsert {
            endpoint: &snapshot.endpoint,
            configured_model: &snapshot.configured_model,
            matched_model: snapshot.matched_model.as_deref(),
            loaded_model: snapshot.loaded_model.as_deref(),
            instance_id: snapshot.instance_id.as_deref(),
            display_name: snapshot.display_name.as_deref(),
            publisher: snapshot.publisher.as_deref(),
            architecture: snapshot.architecture.as_deref(),
            format: snapshot.format.as_deref(),
            params_string: snapshot.params_string.as_deref(),
            quantization: snapshot.quantization.as_deref(),
            selected_variant: snapshot.selected_variant.as_deref(),
            size_bytes: snapshot.size_bytes,
            max_context_length: snapshot.max_context_length,
            capabilities_json: snapshot.capabilities_json.as_deref(),
            desired_load_config_json: &snapshot.desired_load_config_json,
            effective_load_config_json: snapshot.effective_load_config_json.as_deref(),
            health_ok: snapshot.health_ok,
            health_message: &snapshot.health_message,
            model_matches_config: snapshot.model_matches_config,
        };
        insert_runtime_snapshot(&conn, &run_id, &snapshot_id, &insert)
            .map_err(|e| e.to_string())?;

        // Spawn worker threads (each owns its own Connection + single-thread rt).
        let mut handles = Vec::new();
        for (w_idx, batch) in batches.into_iter().enumerate() {
            let params_clone = params.clone();
            let conn_path = params.database_file.clone();
            let run_id_clone = run_id.clone();
            let control_clone = Arc::clone(&control);
            let event_tx_clone = event_tx.clone();
            let process_reason_clone = process_reason.to_string();
            let prompt_id_clone = prompt_snapshot_id.clone();
            let snapshot_id_clone = snapshot_id.clone();

            handles.push(
                std::thread::Builder::new()
                    .name(format!("forza-worker-{w_idx}"))
                    .spawn(move || {
                        let rt = tokio::runtime::Builder::new_current_thread()
                            .enable_all()
                            .build()
                            .unwrap_or_else(|e| panic!("worker {w_idx} tokio runtime: {e}"));
                        rt.block_on(async {
                            worker_loop(
                                w_idx,
                                conn_path,
                                &run_id_clone,
                                batch,
                                &params_clone,
                                control_clone,
                                event_tx_clone,
                                &process_reason_clone,
                                &prompt_id_clone,
                                &snapshot_id_clone,
                            )
                            .await
                        });
                    })
                    .unwrap_or_else(|e| panic!("worker {w_idx} thread spawn: {e}")),
            );
        }
        drop(event_tx);

        // Collect worker results and events.
        let mut w_done = 0usize;
        let mut w_succeeded = 0usize;
        let mut w_failed = 0usize;

        while let Ok(event) = event_rx.recv() {
            match event {
                // Worker progress counters are per-batch; the aggregated
                // monotonic counter is emitted on every ImageDone so the UI
                // never sees a worker-local (e.g. 2/6 twice) number.
                RunEvent::Progress { .. } => {}
                RunEvent::ImageStarted { name: _ } => {
                    on_event(event);
                }
                RunEvent::ImageDone {
                    name: _,
                    ok,
                    laps: _,
                } => {
                    on_event(event);
                    w_done += 1;
                    on_event(RunEvent::Progress {
                        done: w_done,
                        total: total_new,
                    });
                    if ok {
                        w_succeeded += 1;
                    } else {
                        w_failed += 1;
                    }
                }
                RunEvent::Log(line) => {
                    on_event(RunEvent::Log(line));
                }
                _ => {}
            }
        }

        // Wait for all workers to finish. A panicking worker must not be
        // swallowed: its batch was pre-allocated, so mark those results
        // `error` instead of finalizing `completed` with eternal `running`.
        let mut join_failed = 0usize;
        for handle in handles {
            if handle.join().is_err() {
                join_failed += 1;
            }
        }
        if join_failed > 0 {
            on_event(RunEvent::Log(format!(
                "{join_failed} worker thread(s) panicked; affected results marked error"
            )));
        }
        // Safety net: any result still `running` after all workers joined is
        // orphaned (dead worker / early return). Leaving it `running` in a
        // `completed` run hides it from retry_errors forever — mark it error.
        let _ = conn.execute(
            "UPDATE extraction_results SET status='error', error_type='worker_lost',
                    error_message='worker finished without reporting', updated_at=datetime('now')
              WHERE run_id=?1 AND status IN ('pending','running')",
            rusqlite::params![run_id],
        );
        // Pre-insert failures already emitted ImageDone but bypassed the
        // channel counter (channel was cloned per worker set after); count
        // them via pre_failed captured through the event stream instead.
        // (pre_failed events flowed through event_tx above, so w_failed
        // already includes them.)
        let _ = pre_failed;
        backfill_batch_duplicate_links(&conn, &run_id);

        let w_processed = w_succeeded + w_failed;
        (w_processed, w_succeeded, w_failed)
    } else {
        // ── Sequential (single-worker) extraction ───────────────────────
        let mut backend = LMStudioBackend::new(params.backend_config(), Default::default())
            .map_err(|e| e.to_string())?;
        let desired = params.desired_load_config();

        // Deterministic preflight snapshot id — the row itself is only
        // created when the run actually reaches the model.
        let snapshot_id = format!("runtime-{run_id}-preflight");
        if total_new > 0 {
            let snapshot = backend
                .preflight_snapshot(&desired)
                .await
                .map_err(|_| {
                    fail_run_preflight(
                        &conn,
                        &run_id,
                        "LM Studio is not reachable — start LM Studio (with the server on) and try again",
                    )
                })?;
            let insert = RuntimeSnapshotInsert {
                endpoint: &snapshot.endpoint,
                configured_model: &snapshot.configured_model,
                matched_model: snapshot.matched_model.as_deref(),
                loaded_model: snapshot.loaded_model.as_deref(),
                instance_id: snapshot.instance_id.as_deref(),
                display_name: snapshot.display_name.as_deref(),
                publisher: snapshot.publisher.as_deref(),
                architecture: snapshot.architecture.as_deref(),
                format: snapshot.format.as_deref(),
                params_string: snapshot.params_string.as_deref(),
                quantization: snapshot.quantization.as_deref(),
                selected_variant: snapshot.selected_variant.as_deref(),
                size_bytes: snapshot.size_bytes,
                max_context_length: snapshot.max_context_length,
                capabilities_json: snapshot.capabilities_json.as_deref(),
                desired_load_config_json: &snapshot.desired_load_config_json,
                effective_load_config_json: snapshot.effective_load_config_json.as_deref(),
                health_ok: snapshot.health_ok,
                health_message: &snapshot.health_message,
                model_matches_config: snapshot.model_matches_config,
            };
            insert_runtime_snapshot(&conn, &run_id, &snapshot_id, &insert)
                .map_err(|e| e.to_string())?;
        }
        let mut done = 0usize;
        let mut processed = 0usize;
        let mut succeeded = 0usize;
        let mut failed = 0usize;
        for image in &plan.new_images {
            // Safe checkpoint: pause blocks here; cancel stops between images.
            if !control.checkpoint() {
                on_event(RunEvent::Log(
                    "cancellation requested — stopping between images".into(),
                ));
                break;
            }
            input_order += 1;
            processed += 1;
            let name = image
                .path
                .file_name()
                .map(|n| n.to_string_lossy().to_string())
                .unwrap_or_default();
            on_event(RunEvent::ImageStarted { name: name.clone() });

            // Inventory row for this processed image.
            let (image_file_id, _) = upsert_image_for_run(&conn, &image.path, &image.file_hash)
                .map_err(|e| e.to_string())?;

            // Pending result row before the call (status running).
            let (result_id, input_id) = insert_processed_input_full(
                &conn,
                &run_id,
                &image_file_id,
                &image.path.to_string_lossy(),
                process_reason,
                input_order,
            )
            .map_err(|e| e.to_string())?;
            stamp_result_prompt(&conn, &result_id, &prompt_snapshot_id);
            stamp_input_metadata(
                &conn,
                &run_id,
                input_id,
                &image.file_hash,
                &name,
                &image.path,
            );

            // Encode.
            let encoded = match encode_image_payload(
                &image.path,
                params.max_width,
                params.encode_quality,
                &params.image_format,
                params.grayscale,
            ) {
                Ok(payload) => payload,
                Err(e) => {
                    failed += 1;
                    conn.execute(
                        "UPDATE extraction_results SET status='error', error_type='encode', error_message=?2, updated_at=datetime('now') WHERE id=?1",
                        rusqlite::params![result_id, e.to_string()],
                    )
                    .map_err(|e| e.to_string())?;
                    on_event(RunEvent::ImageDone {
                        name: name.clone(),
                        ok: false,
                        laps: 0,
                    });
                    done += 1;
                    on_event(RunEvent::Progress {
                        done,
                        total: total_new,
                    });
                    continue;
                }
            };

            // Ensure the model is loaded (first image or after config change).
            // Per-image error, not a whole-run abort: `?` here used to leave
            // the run and all remaining results stuck in `running`.
            if let Err(e) = backend.ensure_loaded(&desired).await {
                failed += 1;
                let _ = conn.execute(
                    "UPDATE extraction_results SET status='error', error_type='model_load', error_message=?2, updated_at=datetime('now') WHERE id=?1",
                    rusqlite::params![result_id, e.to_string()],
                );
                on_event(RunEvent::ImageDone {
                    name: name.clone(),
                    ok: false,
                    laps: 0,
                });
                on_event(RunEvent::Log(format!("ensure_loaded: {e}")));
                done += 1;
                on_event(RunEvent::Progress {
                    done,
                    total: total_new,
                });
                continue;
            }

            // Extract with attempt persistence.
            let mut attempt_count = 0i64;
            let mut accepted_row: Option<String> = None;
            let extract_result = {
                let conn_ref = &conn;
                let run_id_ref = run_id.clone();
                let image_id = image_file_id.clone();
                let result_id_ref = result_id.clone();
                let model_name = params.model.clone();
                backend
                    .extract(
                        &encoded.data_b64,
                        &encoded.mime_type,
                        &name,
                        Some(&image.file_hash),
                        &mut |record: &ModelAttemptRecord| {
                            attempt_count += 1;
                            if let Some(row_id) = persist_attempt_with_evidence(
                                conn_ref,
                                &run_id_ref,
                                &image_id,
                                &result_id_ref,
                                record,
                                &encoded,
                                &prompt_snapshot_id,
                                &snapshot_id,
                                &image.file_hash,
                                &model_name,
                                Some(params.context_length),
                                params.reasoning_mode.as_deref(),
                            ) {
                                accepted_row = Some(row_id);
                            }
                        },
                    )
                    .await
            };

            match extract_result {
                Ok(result) => {
                    let laps = match crate::services::extraction_replay::derive_and_insert_laps(
                        &conn,
                        &run_id,
                        &image_file_id,
                        &result_id,
                        &result.parsed,
                        Some(&name),
                        Some((params.temp_min_f, params.temp_max_f)),
                    ) {
                        Ok(l) => l,
                        Err(e) => {
                            failed += 1;
                            let _ = conn.execute(
                                "UPDATE extraction_results SET status='error', error_type='laps', error_message=?2, attempt_count=?3, updated_at=datetime('now') WHERE id=?1",
                                rusqlite::params![result_id, e.to_string(), attempt_count],
                            );
                            on_event(RunEvent::ImageDone {
                                name: name.clone(),
                                ok: false,
                                laps: 0,
                            });
                            on_event(RunEvent::Log(format!("laps: {e}")));
                            done += 1;
                            on_event(RunEvent::Progress {
                                done,
                                total: total_new,
                            });
                            continue;
                        }
                    };
                    let stats = forza_db::repositories::runs::ResultStats {
                        model: Some(&params.model),
                        model_instance_id: result.accepted_attempt.model_instance_id.as_deref(),
                        input_tokens: result.accepted_attempt.input_tokens,
                        output_tokens: result.accepted_attempt.output_tokens,
                        reasoning_tokens: result.accepted_attempt.reasoning_tokens,
                        total_tokens: result.accepted_attempt.total_tokens,
                        tokens_per_second: result.accepted_attempt.tokens_per_second,
                        time_to_first_token_s: result.accepted_attempt.time_to_first_token_s,
                        model_load_time_s: result.accepted_attempt.model_load_time_s,
                        duration_ms: result.accepted_attempt.duration_ms,
                    };
                    let Some(row_id) = accepted_row else {
                        failed += 1;
                        let _ = conn.execute(
                            "UPDATE extraction_results SET status='error', error_type='attempt', error_message='accepted attempt row missing', attempt_count=?2, updated_at=datetime('now') WHERE id=?1",
                            rusqlite::params![result_id, attempt_count],
                        );
                        on_event(RunEvent::ImageDone {
                            name: name.clone(),
                            ok: false,
                            laps: 0,
                        });
                        done += 1;
                        on_event(RunEvent::Progress {
                            done,
                            total: total_new,
                        });
                        continue;
                    };
                    forza_db::repositories::runs::finalize_result_ok(
                        &conn,
                        &result_id,
                        &row_id,
                        attempt_count,
                        &stats,
                    )
                    .map_err(|e| e.to_string())?;
                    conn.execute(
                        "UPDATE extraction_results SET request_image_format=?2,
                                request_image_mime_type=?3, request_image_width=?4,
                                request_image_height=?5, request_image_bytes=?6
                         WHERE id=?1",
                        rusqlite::params![
                            result_id,
                            encoded.format,
                            encoded.mime_type,
                            i64::from(encoded.width_px),
                            i64::from(encoded.height_px),
                            encoded.byte_count as i64,
                        ],
                    )
                    .map_err(|e| e.to_string())?;
                    succeeded += 1;
                    if params.verbose {
                        on_event(RunEvent::Log(format!(
                            "[debug] {name} result={result_id} hash={} attempts={attempt_count} attempt={row_id} laps={laps}",
                            image.file_hash,
                        )));
                    }
                    on_event(RunEvent::ImageDone {
                        name: name.clone(),
                        ok: true,
                        laps,
                    });
                }
                Err(err) => {
                    failed += 1;
                    conn.execute(
                        "UPDATE extraction_results SET status='error', error_type='extraction', error_message=?2, attempt_count=?3, updated_at=datetime('now') WHERE id=?1",
                        rusqlite::params![result_id, err.to_string(), attempt_count],
                    )
                    .map_err(|e| e.to_string())?;
                    on_event(RunEvent::ImageDone {
                        name: name.clone(),
                        ok: false,
                        laps: 0,
                    });
                }
            }

            done += 1;
            on_event(RunEvent::Progress {
                done,
                total: total_new,
            });
        }
        (processed, succeeded, failed)
    };

    // ── Run counters + derived refresh ────────────────────────────────────
    backfill_batch_duplicate_links(&conn, &run_id);
    let cancelled = control.is_cancelled();
    let final_status = if cancelled { "cancelled" } else { "completed" };
    complete_run(&conn, &run_id, final_status).map_err(|e| e.to_string())?;

    // Derived refresh parity with Python `_complete_run → rebuild_outputs`:
    // best laps, review cases AND their system flags are recomputed at the
    // end of every run — never requiring a manual Rebuild for reviews to
    // appear. (`rebuild` re-runs `mark_best_laps` idempotently; cheap.)
    match crate::services::rebuild::rebuild(&conn, &params.gamertag) {
        Ok(outcome) => {
            on_event(RunEvent::Log(format!(
                "derived refresh: {} best-lap winner(s), reviews +{} kept {} auto-resolved {} (flags +{}/{})",
                outcome.best_lap_winners,
                outcome.review_inserted,
                outcome.review_kept,
                outcome.review_auto_resolved,
                outcome.flags_ensured,
                outcome.flags_resolved,
            )));
        }
        Err(e) => {
            on_event(RunEvent::Log(format!("derived refresh failed: {e}")));
        }
    }

    Ok((processed, succeeded, failed, 0, 0))
}

/// Persist one backend attempt with the full evidence chain: encoded-image
/// fields, the run's preflight runtime snapshot, and the canonical request
/// hash recomputed from exactly the persisted columns. Both the sequential
/// loop and the parallel workers go through here so the two paths cannot
/// diverge (audit lesson: the sequential path silently missed the stamping).
/// Returns the accepted attempt row id when the attempt was accepted.
#[allow(clippy::too_many_arguments)]
fn persist_attempt_with_evidence(
    conn: &Connection,
    run_id: &str,
    image_file_id: &str,
    result_id: &str,
    record: &ModelAttemptRecord,
    encoded: &forza_pipeline::EncodedImage,
    prompt_snapshot_id: &str,
    runtime_snapshot_id: &str,
    source_file_hash: &str,
    model: &str,
    context_length: Option<i64>,
    reasoning_mode: Option<&str>,
) -> Option<String> {
    let mut insert = crate::services::extraction_replay::to_attempt_insert(
        record,
        model,
        context_length,
        reasoning_mode,
    );
    insert.request_image_format = Some(&encoded.format);
    insert.request_image_mime_type = Some(&encoded.mime_type);
    insert.request_image_width = Some(i64::from(encoded.width_px));
    insert.request_image_height = Some(i64::from(encoded.height_px));
    insert.request_image_bytes = Some(encoded.byte_count as i64);
    insert.runtime_snapshot_id = Some(runtime_snapshot_id);
    let request_hash = forza_db::evidence::canonical_request_hash(
        insert.request_messages_json,
        insert.request_config_json,
        Some(prompt_snapshot_id),
        insert.model,
        Some(source_file_hash),
        insert.request_image_format,
        insert.request_image_mime_type,
        insert.request_image_width,
        insert.request_image_height,
        insert.request_image_bytes,
    );
    insert.request_hash = Some(&request_hash);
    insert_attempt_full_checked(conn, run_id, image_file_id, result_id, &insert)
        .ok()
        .filter(|_| record.accepted)
}

/// Every result retains the immutable prompt snapshot of its run (doctor
/// check `result_prompt_mismatch`).
fn stamp_result_prompt(conn: &Connection, result_id: &str, prompt_snapshot_id: &str) {
    let _ = conn.execute(
        "UPDATE extraction_results SET prompt_snapshot_id=?2 WHERE id=?1",
        rusqlite::params![result_id, prompt_snapshot_id],
    );
}

/// Stamp file-evidence metadata onto a run input by its row id (never by
/// `(run_id, input_order)`: input_order is only unique per run when allocated
/// centrally, and workers must not rely on it as a key).
fn stamp_input_metadata(
    conn: &Connection,
    run_id: &str,
    input_id: i64,
    file_hash: &str,
    name: &str,
    path: &std::path::Path,
) {
    let file_metadata = std::fs::metadata(path).ok();
    let extension = path
        .extension()
        .map(|value| value.to_string_lossy().to_lowercase());
    let size_bytes = file_metadata.as_ref().map(|metadata| metadata.len() as i64);
    let mtime_ns = file_metadata
        .and_then(|metadata| metadata.modified().ok())
        .and_then(|modified| modified.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|duration| duration.as_nanos().min(i64::MAX as u128) as i64);
    let _ = conn.execute(
        "UPDATE run_inputs SET file_hash=?2, file_name=?3, extension=?4,
                normalized_path=?5, size_bytes=?6, mtime_ns=?7
          WHERE id=?1 AND run_id=?8",
        rusqlite::params![
            input_id,
            file_hash,
            name,
            extension,
            path.to_string_lossy().to_string(),
            size_bytes,
            mtime_ns,
            run_id,
        ],
    );
}

/// Link `batch` duplicates to their canonical same-run `process` input.
/// Runs after all process inputs exist (duplicates are recorded before them).
fn backfill_batch_duplicate_links(conn: &Connection, run_id: &str) {
    let _ = conn.execute(
        "UPDATE run_inputs SET duplicate_of_input_id = (
            SELECT p.id FROM run_inputs p
            WHERE p.run_id = run_inputs.run_id
              AND p.decision = 'process'
              AND p.file_hash = run_inputs.duplicate_of_hash
            ORDER BY p.input_order ASC LIMIT 1
        )
        WHERE run_id = ?1 AND decision = 'duplicate' AND duplicate_kind = 'batch'
          AND duplicate_of_input_id IS NULL",
        rusqlite::params![run_id],
    );
}

/// Finalize a run whose LM Studio preflight failed: mark it failed with the
/// canonical operational error so it never lingers as running (Python
/// `fail_preflight_run`). Returns the propagated error message.
fn fail_run_preflight(conn: &Connection, run_id: &str, detail: &str) -> String {
    let message = format!("lmstudio_preflight_failed: {detail}");
    let _ = complete_run(conn, run_id, "failed");
    let _ = conn.execute(
        "UPDATE extraction_runs SET operational_error_code='lmstudio_preflight_failed',
                operational_error_message=?2 WHERE id=?1",
        rusqlite::params![run_id, message],
    );
    message
}

fn path_key(path: &std::path::Path) -> String {
    path.to_string_lossy().replace('/', "\\").to_lowercase()
}

fn selected_image_paths(
    conn: &Connection,
    image_ids: &[String],
) -> Result<std::collections::HashSet<String>, String> {
    let mut paths = std::collections::HashSet::new();
    let mut stmt = conn
        .prepare("SELECT current_path FROM image_files WHERE id=?1")
        .map_err(|e| e.to_string())?;
    for image_id in image_ids {
        if let Ok(path) = stmt.query_row(rusqlite::params![image_id], |row| row.get::<_, String>(0))
        {
            paths.insert(path_key(std::path::Path::new(&path)));
        }
    }
    Ok(paths)
}

fn insert_attempt_full_checked(
    conn: &Connection,
    run_id: &str,
    image_file_id: &str,
    result_id: &str,
    insert: &forza_db::repositories::runs::AttemptInsert<'_>,
) -> Result<String, String> {
    forza_db::repositories::runs::insert_attempt_full(
        conn,
        run_id,
        image_file_id,
        result_id,
        insert,
    )
    .map_err(|e| e.to_string())
}

/// Single-worker loop: owns its own SQLite connection and LMStudioBackend,
/// processes a batch of images sequentially, emits events on `event_tx`.
#[allow(clippy::too_many_arguments)]
async fn worker_loop(
    _w_idx: usize,
    conn_path: PathBuf,
    run_id: &str,
    batch: Vec<WorkerImage>,
    params: &RunParams,
    control: Arc<RunControl>,
    event_tx: std::sync::mpsc::Sender<RunEvent>,
    process_reason: &str,
    prompt_snapshot_id: &str,
    runtime_snapshot_id: &str,
) {
    let conn = match forza_db::open_connection(&conn_path) {
        Ok(c) => c,
        Err(e) => {
            // Never return silently: the collector finalizes `completed`
            // from events, so an unreported batch would vanish without any
            // result row or retry marker.
            let _ = event_tx.send(RunEvent::Log(format!("worker DB open: {e}")));
            for image in &batch {
                let name = image
                    .path
                    .file_name()
                    .map(|n| n.to_string_lossy().to_string())
                    .unwrap_or_default();
                let _ = event_tx.send(RunEvent::ImageDone {
                    name,
                    ok: false,
                    laps: 0,
                });
            }
            return;
        }
    };

    let mut backend = match LMStudioBackend::new(params.backend_config(), Default::default()) {
        Ok(b) => b,
        Err(e) => {
            let _ = event_tx.send(RunEvent::Log(format!("worker backend: {e}")));
            for image in &batch {
                let name = image
                    .path
                    .file_name()
                    .map(|n| n.to_string_lossy().to_string())
                    .unwrap_or_default();
                let _ = conn.execute(
                    "UPDATE extraction_results SET status='error', error_type='worker_backend', error_message=?2, updated_at=datetime('now') WHERE id=?1",
                    rusqlite::params![image.result_id, e.to_string()],
                );
                let _ = event_tx.send(RunEvent::ImageDone {
                    name,
                    ok: false,
                    laps: 0,
                });
            }
            return;
        }
    };

    let desired = params.desired_load_config();

    let total = batch.len();
    let mut done = 0usize;

    for image in batch {
        if !control.checkpoint() {
            let _ = event_tx.send(RunEvent::Log(
                "cancellation requested — stopping between images".into(),
            ));
            break;
        }

        let name = image
            .path
            .file_name()
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_default();

        let _ = event_tx.send(RunEvent::ImageStarted { name: name.clone() });

        // Inputs/results/metadata were pre-allocated on the main connection:
        // resolve the (read-only) image id and process the pre-created result.
        // (`input_id`/`input_order` ride along for traceability; the worker
        // never recomputes keys from them.)
        let _ = (image.input_id, image.input_order);
        let result_id = image.result_id.clone();
        let _ = process_reason;
        let _ = prompt_snapshot_id;
        let image_file_id = match find_image_id_by_hash(&conn, &image.file_hash)
            .map_err(|e| e.to_string())
        {
            Ok(Some(id)) => id,
            Ok(None) => {
                let _ = event_tx.send(RunEvent::ImageDone {
                    name: name.clone(),
                    ok: false,
                    laps: 0,
                });
                let _ = event_tx.send(RunEvent::Log(format!(
                    "image row missing for pre-allocated result {result_id}"
                )));
                let _ = conn.execute(
                    "UPDATE extraction_results SET status='error', error_type='upsert', error_message='image row missing', updated_at=datetime('now') WHERE id=?1",
                    rusqlite::params![result_id],
                );
                done += 1;
                let _ = event_tx.send(RunEvent::Progress { done, total });
                continue;
            }
            Err(e) => {
                let _ = event_tx.send(RunEvent::ImageDone {
                    name: name.clone(),
                    ok: false,
                    laps: 0,
                });
                let _ = event_tx.send(RunEvent::Log(format!("image lookup: {e}")));
                done += 1;
                let _ = event_tx.send(RunEvent::Progress { done, total });
                continue;
            }
        };

        let encoded = match encode_image_payload(
            &image.path,
            params.max_width,
            params.encode_quality,
            &params.image_format,
            params.grayscale,
        ) {
            Ok(payload) => payload,
            Err(e) => {
                let _ = conn.execute(
                    "UPDATE extraction_results SET status='error', error_type='encode', error_message=?2, updated_at=datetime('now') WHERE id=?1",
                    rusqlite::params![result_id, e.to_string()],
                );
                let _ = event_tx.send(RunEvent::ImageDone {
                    name: name.clone(),
                    ok: false,
                    laps: 0,
                });
                done += 1;
                let _ = event_tx.send(RunEvent::Progress { done, total });
                continue;
            }
        };

        match backend.ensure_loaded(&desired).await {
            Ok(()) => {}
            Err(e) => {
                let _ = event_tx.send(RunEvent::ImageDone {
                    name: name.clone(),
                    ok: false,
                    laps: 0,
                });
                let _ = event_tx.send(RunEvent::Log(format!("ensure_loaded: {e}")));
                done += 1;
                let _ = event_tx.send(RunEvent::Progress { done, total });
                let _ = conn.execute(
                    "UPDATE extraction_results SET status='error', error_type='model_load', error_message=?2, updated_at=datetime('now') WHERE id=?1",
                    rusqlite::params![result_id, e.to_string()],
                );
                continue;
            }
        };

        let mut attempt_count = 0i64;
        let mut accepted_row: Option<String> = None;
        let model_name = params.model.clone();
        let extract_result = backend
            .extract(
                &encoded.data_b64,
                &encoded.mime_type,
                &name,
                Some(&image.file_hash),
                &mut |record: &ModelAttemptRecord| {
                    attempt_count += 1;
                    if let Some(row_id) = persist_attempt_with_evidence(
                        &conn,
                        run_id,
                        &image_file_id,
                        &result_id,
                        record,
                        &encoded,
                        prompt_snapshot_id,
                        runtime_snapshot_id,
                        &image.file_hash,
                        &model_name,
                        Some(params.context_length),
                        params.reasoning_mode.as_deref(),
                    ) {
                        accepted_row = Some(row_id);
                    }
                },
            )
            .await;

        match extract_result {
            Ok(result) => {
                let laps = match crate::services::extraction_replay::derive_and_insert_laps(
                    &conn,
                    run_id,
                    &image_file_id,
                    &result_id,
                    &result.parsed,
                    Some(&name),
                    Some((params.temp_min_f, params.temp_max_f)),
                ) {
                    Ok(l) => l,
                    Err(e) => {
                        // Never leave the result `running`: a laps failure is
                        // a per-image error, visible to retry_errors.
                        let _ = conn.execute(
                            "UPDATE extraction_results SET status='error', error_type='laps', error_message=?2, attempt_count=?3, updated_at=datetime('now') WHERE id=?1",
                            rusqlite::params![result_id, e.to_string(), attempt_count],
                        );
                        let _ = event_tx.send(RunEvent::ImageDone {
                            name: name.clone(),
                            ok: false,
                            laps: 0,
                        });
                        let _ = event_tx.send(RunEvent::Log(format!("laps: {e}")));
                        done += 1;
                        let _ = event_tx.send(RunEvent::Progress { done, total });
                        continue;
                    }
                };
                let stats = forza_db::repositories::runs::ResultStats {
                    model: Some(&params.model),
                    model_instance_id: result.accepted_attempt.model_instance_id.as_deref(),
                    input_tokens: result.accepted_attempt.input_tokens,
                    output_tokens: result.accepted_attempt.output_tokens,
                    reasoning_tokens: result.accepted_attempt.reasoning_tokens,
                    total_tokens: result.accepted_attempt.total_tokens,
                    tokens_per_second: result.accepted_attempt.tokens_per_second,
                    time_to_first_token_s: result.accepted_attempt.time_to_first_token_s,
                    model_load_time_s: result.accepted_attempt.model_load_time_s,
                    duration_ms: result.accepted_attempt.duration_ms,
                };
                // Never stream ok:true while the DB row is still `running`:
                // a failed finalize must surface as ok:false + error row.
                let finalize_outcome: Result<(), String> = (|| {
                    let Some(row_id) = accepted_row else {
                        return Err(
                            "accepted attempt row missing (attempt insert failed)".to_string()
                        );
                    };
                    forza_db::repositories::runs::finalize_result_ok(
                        &conn,
                        &result_id,
                        &row_id,
                        attempt_count,
                        &stats,
                    )
                    .map_err(|e| e.to_string())?;
                    conn.execute(
                        "UPDATE extraction_results SET request_image_format=?2,
                                request_image_mime_type=?3, request_image_width=?4,
                                request_image_height=?5, request_image_bytes=?6
                         WHERE id=?1",
                        rusqlite::params![
                            result_id,
                            encoded.format,
                            encoded.mime_type,
                            i64::from(encoded.width_px),
                            i64::from(encoded.height_px),
                            encoded.byte_count as i64,
                        ],
                    )
                    .map_err(|e| e.to_string())?;
                    Ok(())
                })();
                match finalize_outcome {
                    Ok(()) => {
                        if params.verbose {
                            let _ = event_tx.send(RunEvent::Log(format!(
                                "[debug] {name} result={result_id} hash={} attempts={attempt_count} laps={laps} (worker)",
                                image.file_hash,
                            )));
                        }
                        let _ = event_tx.send(RunEvent::ImageDone {
                            name: name.clone(),
                            ok: true,
                            laps,
                        });
                    }
                    Err(e) => {
                        let _ = conn.execute(
                            "UPDATE extraction_results SET status='error', error_type='finalize', error_message=?2, attempt_count=?3, updated_at=datetime('now') WHERE id=?1",
                            rusqlite::params![result_id, e, attempt_count],
                        );
                        let _ = event_tx.send(RunEvent::ImageDone {
                            name: name.clone(),
                            ok: false,
                            laps: 0,
                        });
                        let _ = event_tx.send(RunEvent::Log(format!("finalize {result_id}: {e}")));
                    }
                }
            }
            Err(err) => {
                let _ = conn.execute(
                    "UPDATE extraction_results SET status='error', error_type='extraction', error_message=?2, attempt_count=?3, updated_at=datetime('now') WHERE id=?1",
                    rusqlite::params![result_id, err.to_string(), attempt_count],
                );
                let _ = event_tx.send(RunEvent::ImageDone {
                    name: name.clone(),
                    ok: false,
                    laps: 0,
                });
            }
        }

        done += 1;
        let _ = event_tx.send(RunEvent::Progress { done, total });
    }
}
