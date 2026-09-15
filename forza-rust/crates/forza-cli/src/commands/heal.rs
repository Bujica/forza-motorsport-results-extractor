//! `maintenance db-heal` command and its heal helpers.

use std::path::Path;

/// Backfill the evidence chain on rows produced by builds that predate the
/// request_hash/runtime_snapshot_id/prompt_snapshot_id stamping. Only rows
/// failing the corresponding doctor checks are touched; values are derived
/// with the same canonical implementation the doctor recomputes with.
pub(crate) fn cmd_db_heal(config_path: &Path, db_path: &Path) -> anyhow::Result<()> {
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
        let expected =
            forza_db::evidence::canonical_request_hash(&forza_db::evidence::RequestFingerprint {
                request_messages_json: messages.as_deref(),
                request_config_json: config.as_deref(),
                prompt_snapshot_id: prompt_id.as_deref(),
                model: model.as_deref(),
                source_file_hash: source_hash.as_deref(),
                request_image_format: image_format.as_deref(),
                request_image_mime_type: image_mime.as_deref(),
                request_image_width: width,
                request_image_height: height,
                request_image_bytes: bytes,
            });
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
            &forza_db::ImageFileId::new(image_id),
            std::path::Path::new(current_path),
            &forza_db::ExtractionResultId::new(result_id),
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

    // 5. Laps: null temps persisted outside the validation window by
    //    builds predating the insert-time gate (same window the live path
    //    and Python enforce).
    let (temp_min, temp_max) = match forza_config::load_config(config_path, false) {
        Ok((cfg, _)) => (cfg.validation.temp_min_f, cfg.validation.temp_max_f),
        Err(_) => forza_domain::lap::DEFAULT_TEMP_RANGE_F,
    };
    let temps_healed = heal_out_of_window_temps(&conn, temp_min, temp_max)?;

    // 6. Inputs: drop duplicate rows orphaned by image deletes (their links
    //    rot and their run counters lie until then).
    let orphan_inputs_healed = heal_orphan_duplicate_inputs(&conn)?;
    // Recompute counters: the delete above changes duplicate_count/total.
    let _ = conn.execute(
        "UPDATE extraction_runs SET
            total_inputs = (SELECT COUNT(*) FROM run_inputs WHERE run_id = extraction_runs.id),
            duplicate_count = (SELECT COUNT(*) FROM run_inputs WHERE run_id = extraction_runs.id
                               AND decision = 'duplicate')
         WHERE status != 'running'",
        [],
    )?;

    println!("db-heal: evidence backfill complete");
    println!("  abandoned runs reconciled  : {reconciled} run(s)");
    println!("  run counters recomputed    : {counters_healed} run(s)");
    println!("  results.prompt_snapshot_id : {results_healed} row(s)");
    println!("  attempts.runtime_snapshot  : {runtime_healed} row(s)");
    println!("  attempts.request_hash      : {hashes_healed} row(s)");
    println!("  images.semantic_name       : {names_healed} row(s)");
    println!("  laps.out_of_window_temp    : {temps_healed} row(s)");
    println!("  run_inputs.orphan_duplicate: {orphan_inputs_healed} row(s)");
    println!("next step: run `forza rebuild` to refresh best-lap status and review cases");
    Ok(())
}

/// Drop duplicate inputs orphaned by image deletes.
///
/// Duplicate inputs always reference their own image row (runner parity with
/// Python); a NULL image means the image is gone and no flow will ever clean
/// the row — it only rots links and counters. Running runs are excluded
/// (their inputs are still being written). Rows targeted by a surviving link
/// are kept: deleting them would NULL a live link and trade one doctor
/// error for another.
fn heal_orphan_duplicate_inputs(conn: &rusqlite::Connection) -> anyhow::Result<usize> {
    let healed = conn.execute(
        "DELETE FROM run_inputs
         WHERE image_file_id IS NULL AND decision = 'duplicate'
           AND run_id IN (SELECT id FROM extraction_runs WHERE status != 'running')
           AND id NOT IN (
               SELECT keeper.duplicate_of_input_id FROM run_inputs keeper
               WHERE keeper.duplicate_of_input_id IS NOT NULL
                 AND NOT (keeper.image_file_id IS NULL
                          AND keeper.decision = 'duplicate'
                          AND keeper.run_id IN (SELECT id FROM extraction_runs
                                                WHERE status != 'running'))
           )",
        [],
    )?;
    Ok(healed)
}

/// Null out-of-window lap temperatures produced before the insert-time gate
/// (Python parity: `process_image` persists `temp_f` only inside
/// `[validation] temp_min_f/temp_max_f`). Without this, old rows keep raw
/// values that skew the temperature-aware frontier after rebuild.
fn heal_out_of_window_temps(
    conn: &rusqlite::Connection,
    temp_min: f64,
    temp_max: f64,
) -> anyhow::Result<usize> {
    let healed = conn.execute(
        "UPDATE lap_records SET temp_f = NULL, temp_c = NULL
         WHERE temp_f IS NOT NULL AND (temp_f < ?1 OR temp_f > ?2)",
        rusqlite::params![temp_min, temp_max],
    )?;
    Ok(healed)
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;

    #[test]
    fn heal_nulls_only_out_of_window_temps() {
        let dir = tempfile::tempdir().unwrap();
        let db = dir.path().join("heal.sqlite3");
        forza_db::upgrade(&db).unwrap();
        let conn = forza_db::open_connection(&db).unwrap();
        conn.execute_batch(
            "INSERT INTO image_files (id, file_hash, first_seen_at, created_at, updated_at)
             VALUES ('img-h', 'h', datetime('now'), datetime('now'), datetime('now'));
             INSERT INTO extraction_runs (id, status, mode, model, created_at)
             VALUES ('run-h', 'completed', 'normal', 'm', datetime('now'));
             INSERT INTO run_inputs (id, run_id, input_order, input_path, decision, created_at)
             VALUES (1, 'run-h', 0, 'h.png', 'process', datetime('now'));
             INSERT INTO extraction_results (id, run_id, run_input_id, image_file_id, status, created_at)
             VALUES ('res-h', 'run-h', 1, 'img-h', 'ok', datetime('now'));
             INSERT INTO lap_records (id, run_id, image_file_id, extraction_result_id, lap_index, best_lap_ms, temp_f, temp_c, created_at)
             VALUES ('lap-cold', 'run-h', 'img-h', 'res-h', 0, 90000, 24.0, NULL, datetime('now')),
                    ('lap-ok', 'run-h', 'img-h', 'res-h', 1, 91000, 72.0, 22.2, datetime('now')),
                     ('lap-null', 'run-h', 'img-h', 'res-h', 2, 92000, NULL, NULL, datetime('now'));",
        )
        .unwrap();

        let healed = heal_out_of_window_temps(&conn, 40.0, 140.0).unwrap();
        assert_eq!(healed, 1);
        let temps: Vec<(Option<f64>, Option<f64>)> = conn
            .prepare("SELECT temp_f, temp_c FROM lap_records ORDER BY lap_index")
            .unwrap()
            .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))
            .unwrap()
            .collect::<Result<Vec<_>, _>>()
            .unwrap();
        assert_eq!(
            temps,
            vec![(None, None), (Some(72.0), Some(22.2)), (None, None)]
        );
    }

    #[test]
    fn heal_drops_orphan_duplicate_inputs_but_keeps_live_targets() {
        let dir = tempfile::tempdir().unwrap();
        let db = dir.path().join("healorphan.sqlite3");
        forza_db::upgrade(&db).unwrap();
        let conn = forza_db::open_connection(&db).unwrap();
        conn.execute_batch(
            "INSERT INTO extraction_runs (id, status, mode, model, created_at)
             VALUES ('run-o', 'completed', 'normal', 'm', datetime('now')),
                    ('run-live', 'running', 'normal', 'm', datetime('now'));
             INSERT INTO image_files (id, file_hash, first_seen_at, created_at, updated_at)
             VALUES ('img-live', 'hash-1', datetime('now'), datetime('now'), datetime('now'));
             INSERT INTO run_inputs (id, run_id, image_file_id, input_order, input_path,
                                     decision, file_hash, duplicate_kind, duplicate_of_hash,
                                     duplicate_of_input_id, created_at)
             VALUES (1, 'run-o', NULL, 0, 'gone-a.png', 'duplicate',
                     'hash-1', 'batch', 'hash-1', NULL, datetime('now')),
                    (2, 'run-o', NULL, 1, 'gone-b.png', 'duplicate',
                     'hash-1', 'batch', 'hash-1', 3, datetime('now')),
                    (3, 'run-o', 'img-live', 2, 'live.png', 'process',
                     'hash-1', NULL, NULL, NULL, datetime('now')),
                    (4, 'run-o', NULL, 3, 'gone-c.png', 'duplicate',
                     'hash-1', 'batch', 'hash-1', NULL, datetime('now')),
                    (5, 'run-live', NULL, 0, 'live-dup.png', 'duplicate',
                     'hash-1', 'batch', 'hash-1', 4, datetime('now'));",
        )
        .unwrap();

        // Rows 1-2 are fully orphaned. Row 4 is NULL-image but targeted by
        // row 5, which survives (running run): deleting 4 would NULL a live
        // link, so 4 stays. Row 5 stays (running run).
        let healed = heal_orphan_duplicate_inputs(&conn).unwrap();
        assert_eq!(healed, 2);
        let remaining: Vec<i64> = conn
            .prepare("SELECT id FROM run_inputs ORDER BY id")
            .unwrap()
            .query_map([], |r| r.get(0))
            .unwrap()
            .collect::<Result<Vec<_>, _>>()
            .unwrap();
        assert_eq!(remaining, vec![3, 4, 5]);
    }
}
