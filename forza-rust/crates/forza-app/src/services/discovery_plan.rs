//! Single owner for run-discovery planning.
//!
//! `forza-cli::cmd_run --dry-run` and `extraction_runner::run_async` built the
//! same `ImageDiscoveryPlan` twice with already-diverged behavior (audit:
//! re-hash failure was `SKIP` in the CLI but `unwrap_or(stale hash)` in the
//! runner). Both callers go through [`build_discovery_plan`] so retry/force/
//! limit/selected-ids rules cannot diverge again.
//!
//! Policy (unified, CLI-strict wins where the copies disagreed):
//! - `force` + `retry_errors` is rejected (Python run contract).
//! - Retry mode replaces discovery: only images whose latest result is `error`
//!   and still exist on disk are planned. A failed live re-hash means the file
//!   cannot be trusted for dedup, so it is skipped loudly via `log` instead of
//!   being planned under a stale identity.
//! - Otherwise: `find_images` (+ optional `selected_image_file_ids` filter) +
//!   `plan_images` against known hashes/paths.
//! - `limit` truncates `new_images` and resets `plan.total` to the truncated
//!   count (the work this invocation can perform, not pre-cap discovery).
//! - Per-file skip lines go through `log` (callers map it to `eprintln!` or
//!   `RunEvent::Log`); the one-line retry summary is left to callers because
//!   the CLI and runner formats differ.

use std::collections::HashSet;
use std::path::Path;

use rusqlite::Connection;

use forza_pipeline::planning::{DiscoveredImage, ImageDiscoveryPlan};

use super::path_key;

/// Input for [`build_discovery_plan`]. `selected_image_file_ids` is `None` in
/// the CLI (no inventory selection there) and `Some` for GUI "selected run"s.
pub struct DiscoveryInput<'a> {
    pub conn: &'a Connection,
    pub input_dir: &'a Path,
    pub force: bool,
    pub retry_errors: bool,
    pub limit: Option<usize>,
    pub selected_image_file_ids: Option<&'a [String]>,
}

/// Output of [`build_discovery_plan`].
#[derive(Debug)]
pub struct DiscoveryOutput {
    pub plan: ImageDiscoveryPlan,
    /// True when the DB knew nothing (first run). Only meaningful outside
    /// retry mode; always false for retry plans.
    pub inventory_empty: bool,
    /// Retry candidates missing on disk (ignored). Always 0 outside retry.
    pub missing_retry: usize,
}

/// Build the run plan. See module docs for the unified policy.
pub fn build_discovery_plan(
    inp: DiscoveryInput<'_>,
    log: &mut dyn FnMut(String),
) -> Result<DiscoveryOutput, String> {
    if inp.force && inp.retry_errors {
        return Err("--force and --retry-errors cannot be combined.".into());
    }

    if inp.retry_errors {
        let failed = forza_db::repositories::list_failed_images_for_retry(inp.conn)
            .map_err(|e| e.to_string())?;
        let mut new_images = Vec::new();
        let mut missing = 0usize;
        for (path, _stored_hash) in failed {
            let candidate = std::path::PathBuf::from(&path);
            if candidate.exists() {
                // Never silently reuse the stored hash: a failed re-hash means
                // the file cannot be trusted for dedup, so skip loudly instead
                // of planning it under a stale identity.
                match forza_pipeline::file_hash(&candidate) {
                    Ok(live_hash) => new_images.push(DiscoveredImage {
                        path: candidate,
                        file_hash: live_hash,
                    }),
                    Err(e) => {
                        log(format!(
                            "SKIP {} (re-hash failed: {e})",
                            candidate.display()
                        ));
                    }
                }
            } else {
                missing += 1;
            }
        }
        let total = new_images.len();
        let mut plan = ImageDiscoveryPlan {
            total,
            new_images,
            duplicates: Vec::new(),
            existing_images: Vec::new(),
            skipped_images: Vec::new(),
        };
        if let Some(limit) = inp.limit {
            plan.new_images.truncate(limit);
            plan.total = plan.new_images.len();
        }
        return Ok(DiscoveryOutput {
            plan,
            inventory_empty: false,
            missing_retry: missing,
        });
    }

    let mut images = forza_pipeline::find_images(inp.input_dir);
    if let Some(selected_ids) = inp.selected_image_file_ids {
        let selected_paths = selected_image_paths(inp.conn, selected_ids)?;
        images.retain(|image| selected_paths.contains(&path_key(image)));
    }
    let known_paths =
        forza_db::repositories::known_path_hashes(inp.conn).map_err(|e| e.to_string())?;
    let known_set = forza_db::repositories::known_hashes(inp.conn).map_err(|e| e.to_string())?;
    let inventory_empty = known_set.is_empty() && known_paths.is_empty();
    let mut plan = forza_pipeline::plan_images(&images, &known_set, &known_paths, inp.force)
        .map_err(|e| e.to_string())?;
    // Python's inventory register step logs every duplicate skip in place.
    let _skipped_duplicates = forza_pipeline::log_duplicate_skips(&plan);
    if let Some(limit) = inp.limit {
        plan.new_images.truncate(limit);
        // The plan describes the work this invocation can actually perform,
        // not the number of files discovered before applying the cap.
        plan.total = plan.new_images.len();
    }
    Ok(DiscoveryOutput {
        plan,
        inventory_empty,
        missing_retry: 0,
    })
}

fn selected_image_paths(
    conn: &Connection,
    image_ids: &[String],
) -> Result<HashSet<String>, String> {
    let mut paths = HashSet::new();
    for image_id in image_ids {
        if let Ok(Some(path)) =
            forza_db::repositories::image_current_path(conn, image_id).map_err(|e| e.to_string())
        {
            paths.insert(path_key(Path::new(&path)));
        }
    }
    Ok(paths)
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;

    fn write_png(path: &Path, w: u32, h: u32, seed: u8) {
        let img = image::RgbImage::from_fn(w, h, |x, y| {
            image::Rgb([
                (x % 251) as u8,
                (y % 251) as u8,
                x.wrapping_add(y).wrapping_add(seed as u32) as u8,
            ])
        });
        img.save_with_format(path, image::ImageFormat::Png).unwrap();
    }

    fn open_db() -> (tempfile::TempDir, Connection) {
        let dir = tempfile::tempdir().unwrap();
        let db = dir.path().join("t.sqlite3");
        forza_db::upgrade(&db).unwrap();
        let conn = forza_db::open_connection(&db).unwrap();
        (dir, conn)
    }

    #[test]
    fn force_and_retry_is_rejected() {
        let (_d, conn) = open_db();
        let dir = tempfile::tempdir().unwrap();
        let mut logs = Vec::new();
        let err = build_discovery_plan(
            DiscoveryInput {
                conn: &conn,
                input_dir: dir.path(),
                force: true,
                retry_errors: true,
                limit: None,
                selected_image_file_ids: None,
            },
            &mut |line| logs.push(line),
        )
        .unwrap_err();
        assert!(err.contains("cannot be combined"));
    }

    #[test]
    fn empty_dir_plans_nothing() {
        let (_d, conn) = open_db();
        let dir = tempfile::tempdir().unwrap();
        let mut logs = Vec::new();
        let out = build_discovery_plan(
            DiscoveryInput {
                conn: &conn,
                input_dir: dir.path(),
                force: false,
                retry_errors: false,
                limit: None,
                selected_image_file_ids: None,
            },
            &mut |line| logs.push(line),
        )
        .unwrap();
        assert_eq!(out.plan.process_count(), 0);
        assert!(out.inventory_empty);
        assert_eq!(out.missing_retry, 0);
    }

    #[test]
    fn retry_with_no_failed_images_is_empty() {
        let (_d, conn) = open_db();
        let dir = tempfile::tempdir().unwrap();
        let mut logs = Vec::new();
        let out = build_discovery_plan(
            DiscoveryInput {
                conn: &conn,
                input_dir: dir.path(),
                force: false,
                retry_errors: true,
                limit: None,
                selected_image_file_ids: None,
            },
            &mut |line| logs.push(line),
        )
        .unwrap();
        assert_eq!(out.plan.process_count(), 0);
        assert!(!out.inventory_empty);
    }

    #[test]
    fn limit_truncates_and_resets_total() {
        let (_d, conn) = open_db();
        let dir = tempfile::tempdir().unwrap();
        write_png(&dir.path().join("a.png"), 16, 16, 1);
        write_png(&dir.path().join("b.png"), 16, 16, 2);
        write_png(&dir.path().join("c.png"), 16, 16, 3);
        let mut logs = Vec::new();
        let out = build_discovery_plan(
            DiscoveryInput {
                conn: &conn,
                input_dir: dir.path(),
                force: false,
                retry_errors: false,
                limit: Some(2),
                selected_image_file_ids: None,
            },
            &mut |line| logs.push(line),
        )
        .unwrap();
        assert_eq!(out.plan.process_count(), 2);
        assert_eq!(out.plan.total, 2);
    }

    #[test]
    fn retry_skips_missing_files_and_counts_them() {
        let (_d, conn) = open_db();
        let dir = tempfile::tempdir().unwrap();
        // Seed a failed result pointing at a file that no longer exists.
        // `list_failed_images_for_retry` reads current_path/file_hash from
        // image_files with file_status='available'.
        let missing_path = dir.path().join("gone.png").display().to_string();
        conn.execute(
            "INSERT INTO image_files
               (id, file_hash, current_name, current_path, file_status,
                first_seen_at, created_at, updated_at)
             VALUES ('img-m', 'h', 'gone.png', ?1, 'available',
                     datetime('now'), datetime('now'), datetime('now'))",
            rusqlite::params![missing_path],
        )
        .unwrap();
        conn.execute_batch(
            "INSERT INTO extraction_runs (id, status, mode, model, created_at)
             VALUES ('run-m', 'completed', 'normal', 'm', datetime('now'));
             INSERT INTO run_inputs (id, run_id, input_order, input_path, decision, created_at)
             VALUES (1, 'run-m', 0, 'gone.png', 'process', datetime('now'));
             INSERT INTO extraction_results (id, run_id, run_input_id, image_file_id, status, created_at)
             VALUES ('res-m', 'run-m', 1, 'img-m', 'error', datetime('now'));",
        )
        .unwrap();
        let mut logs = Vec::new();
        let out = build_discovery_plan(
            DiscoveryInput {
                conn: &conn,
                input_dir: dir.path(),
                force: false,
                retry_errors: true,
                limit: None,
                selected_image_file_ids: None,
            },
            &mut |line| logs.push(line),
        )
        .unwrap();
        assert_eq!(out.plan.process_count(), 0);
        assert_eq!(out.missing_retry, 1);
    }

    #[test]
    fn retry_limit_reports_post_cut_counts() {
        // Intentional semantics: summaries built from the plan ("retry: N
        // selected", "new=") describe the work actually planned, after the
        // cap — not the eligible total before it.
        let (_d, conn) = open_db();
        let dir = tempfile::tempdir().unwrap();
        for (i, seed) in [(1, 11u8), (2, 22), (3, 33)] {
            let name = format!("r{i}.png");
            write_png(&dir.path().join(&name), 16, 16, seed);
            let live = format!("live-{i}");
            conn.execute(
                "INSERT INTO image_files
                   (id, file_hash, current_name, current_path, file_status,
                    first_seen_at, created_at, updated_at)
                 VALUES (?1, ?2, ?3, ?4, 'available',
                         datetime('now'), datetime('now'), datetime('now'))",
                rusqlite::params![
                    format!("img-r{i}"),
                    live,
                    name,
                    dir.path().join(&name).display().to_string(),
                ],
            )
            .unwrap();
            conn.execute_batch(&format!(
                "INSERT INTO extraction_runs (id, status, mode, model, created_at)
                 VALUES ('run-r{i}', 'completed', 'normal', 'm', datetime('now'));
                 INSERT INTO run_inputs (id, run_id, input_order, input_path, decision, created_at)
                 VALUES ({i}, 'run-r{i}', 0, '{name}', 'process', datetime('now'));
                 INSERT INTO extraction_results (id, run_id, run_input_id, image_file_id, status, created_at)
                 VALUES ('res-r{i}', 'run-r{i}', {i}, 'img-r{i}', 'error', datetime('now'));"
            ))
            .unwrap();
        }
        let mut logs = Vec::new();
        let out = build_discovery_plan(
            DiscoveryInput {
                conn: &conn,
                input_dir: dir.path(),
                force: false,
                retry_errors: true,
                limit: Some(2),
                selected_image_file_ids: None,
            },
            &mut |line| logs.push(line),
        )
        .unwrap();
        assert_eq!(out.plan.process_count(), 2);
        assert_eq!(out.plan.total, 2);
        assert_eq!(out.missing_retry, 0);
    }
}
