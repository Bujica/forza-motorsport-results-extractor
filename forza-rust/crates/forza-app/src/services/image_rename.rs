//! Metadata-based image rename with plan preview and series management.
//!
//! Port of Python `ImageRenameService`: renaming is a user-facing file
//! operation only — extraction never depends on it. The flow is always
//! plan-first (`plan_rename_many`, dry, no filesystem or DB writes) and then
//! execute (`rename_files`), so the GUI can show a
//! `source -> target` preview with totals before anything moves.
//!
//! Repeated semantic names share one filename series (`"Name - Race 001.ext"`)
//! computed against ALL available images plus on-disk occupants, so renaming
//! a batch never collides the way naive per-file renames do.

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

use rusqlite::{Connection, params};

const WIN_FORBIDDEN: &[char] = &['<', '>', ':', '"', '/', '\\', '|', '?', '*'];
const WIN_RESERVED: &[&str] = &[
    "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8",
    "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
];

/// One planned rename: pure decision, no side effects.
#[derive(Debug, Clone, PartialEq)]
pub struct RenamePlan {
    pub image_file_id: String,
    pub source: PathBuf,
    pub target: PathBuf,
    pub semantic_name: String,
    pub would_change: bool,
    /// `semantic_name` | `already_named` | `missing_image`.
    pub reason: &'static str,
}

/// Per-file execution outcome.
#[derive(Debug, Clone, PartialEq)]
pub struct RenameOutcome {
    pub plan: RenamePlan,
    pub renamed: bool,
    pub error: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Default)]
pub struct RenamePreview {
    pub plans: Vec<RenamePlan>,
    pub total: usize,
    pub would_change: usize,
    pub missing: usize,
}

#[derive(Debug, Clone)]
struct ImageRow {
    id: String,
    current_path: String,
    current_name: Option<String>,
    semantic_name: Option<String>,
    race_datetime: Option<String>,
}

fn load_images(conn: &Connection, ids: &[String]) -> Result<Vec<ImageRow>, String> {
    let mut out = Vec::new();
    for chunk in ids.chunks(900) {
        if chunk.is_empty() {
            continue;
        }
        let placeholders = chunk.iter().map(|_| "?").collect::<Vec<_>>().join(",");
        let sql = format!(
            "SELECT id, current_path, current_name, semantic_name, race_datetime
             FROM image_files WHERE id IN ({placeholders})"
        );
        let mut stmt = conn.prepare(&sql).map_err(|e| e.to_string())?;
        let params: Vec<&dyn rusqlite::types::ToSql> = chunk
            .iter()
            .map(|id| id as &dyn rusqlite::types::ToSql)
            .collect();
        let rows = stmt
            .query_map(params.as_slice(), |r| {
                Ok(ImageRow {
                    id: r.get(0)?,
                    current_path: r.get(1)?,
                    current_name: r.get(2)?,
                    semantic_name: r.get(3)?,
                    race_datetime: r.get(4)?,
                })
            })
            .map_err(|e| e.to_string())?;
        for row in rows {
            out.push(row.map_err(|e| e.to_string())?);
        }
    }
    // Preserve caller order; unknown ids are simply absent (callers report
    // them as missing by diffing against the input list, like Python).
    let mut by_id: HashMap<String, ImageRow> = HashMap::new();
    for row in out {
        by_id.insert(row.id.clone(), row);
    }
    Ok(ids.iter().filter_map(|id| by_id.remove(id)).collect())
}

/// Preferred display name: semantic, else current, else fallback.
fn preferred_name(image: &ImageRow) -> String {
    image
        .semantic_name
        .clone()
        .filter(|s| !s.trim().is_empty())
        .or_else(|| image.current_name.clone())
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| "image".to_string())
}

/// Windows-safe filename, keeping the source suffix (Python parity incl. the
/// full COM/LPT reserved list).
fn safe_filename(name: &str, fallback_suffix: &str) -> String {
    let suffix = Path::new(name)
        .extension()
        .map(|e| format!(".{}", e.to_string_lossy()))
        .filter(|s| s != ".")
        .unwrap_or_else(|| fallback_suffix.to_string());
    let stem = Path::new(name)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or(name);
    let mut clean: String = stem
        .chars()
        .filter(|c| !WIN_FORBIDDEN.contains(c) && !c.is_control())
        .collect();
    clean = clean
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .trim()
        .trim_end_matches('.')
        .to_string();
    if clean.is_empty() {
        clean = "image".into();
    }
    if WIN_RESERVED.contains(&clean.to_uppercase().as_str()) {
        clean.push('_');
    }
    format!("{}{}", clean.chars().take(200).collect::<String>(), suffix)
}

/// Case-insensitive path identity (Windows filesystem parity).
fn path_key(path: &Path) -> String {
    path.to_string_lossy().to_lowercase().replace('/', "\\")
}

/// Series number of `path` within `base_target`'s `" - Race NNN"` series:
/// base stem itself is 0, otherwise the numeric suffix, else `None`.
fn series_number(path: &Path, base_target: &Path) -> Option<u32> {
    if path.parent() != base_target.parent() {
        return None;
    }
    let suffix_eq = path.extension().map(|e| e.to_string_lossy().to_lowercase())
        == base_target
            .extension()
            .map(|e| e.to_string_lossy().to_lowercase());
    if !suffix_eq {
        return None;
    }
    let stem = path.file_stem()?.to_string_lossy().to_lowercase();
    let base_stem = base_target.file_stem()?.to_string_lossy().to_lowercase();
    if stem == base_stem {
        return Some(0);
    }
    let prefix = format!("{base_stem} - race ");
    let rest = stem.strip_prefix(prefix.as_str())?;
    rest.parse::<u32>().ok()
}

fn indexed_target(base_target: &Path, index: u32) -> PathBuf {
    let stem = base_target
        .file_stem()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_default();
    let suffix = base_target
        .extension()
        .map(|e| format!(".{}", e.to_string_lossy()))
        .unwrap_or_default();
    base_target.with_file_name(format!("{stem} - Race {index:03}{suffix}"))
}

/// Numbers already taken on disk for a series, optionally excluding paths
/// that are moving away as part of this same batch.
fn occupied_series_numbers(base_target: &Path, excluding_paths: &HashSet<String>) -> HashSet<u32> {
    let parent = match base_target.parent() {
        Some(p) => p,
        None => return HashSet::new(),
    };
    let entries = match std::fs::read_dir(parent) {
        Ok(entries) => entries,
        Err(_) => return HashSet::new(),
    };
    entries
        .filter_map(|e| e.ok().map(|entry| entry.path()))
        .filter_map(|entry| {
            let number = series_number(&entry, base_target)?;
            if excluding_paths.contains(&path_key(&entry)) {
                None
            } else {
                Some(number)
            }
        })
        .collect()
}

/// Group key for one semantic-name series: parent dir + stem + suffix.
type SeriesKey = (PathBuf, String, String);

/// Chronological order within a series: race datetime, else file mtime, else
/// path fallback (Python `_race_order_key` parity).
fn race_order_key(image: &ImageRow) -> (u8, f64, String, String) {
    let source = PathBuf::from(&image.current_path);
    if let Some(raw) = image.race_datetime.as_deref()
        && let Ok(dt) = chrono::DateTime::parse_from_rfc3339(raw)
    {
        return (
            0,
            dt.timestamp() as f64,
            source.to_string_lossy().to_lowercase(),
            image.id.clone(),
        );
    }
    if let Ok(meta) = std::fs::metadata(&source)
        && let Ok(mtime) = meta.modified().and_then(|t| {
            t.duration_since(std::time::UNIX_EPOCH)
                .map_err(|_| std::io::Error::other("clock"))
        })
    {
        return (
            1,
            mtime.as_secs_f64(),
            source.to_string_lossy().to_lowercase(),
            image.id.clone(),
        );
    }
    (
        2,
        0.0,
        source.to_string_lossy().to_lowercase(),
        image.id.clone(),
    )
}

/// All available images grouped by their would-be semantic target: the
/// reference for deciding complete vs partial series.
fn available_semantic_group_ids(
    conn: &Connection,
) -> Result<HashMap<SeriesKey, HashSet<String>>, String> {
    let mut stmt = conn
        .prepare("SELECT id, current_path, current_name, semantic_name FROM image_files WHERE file_status = 'available'")
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, Option<String>>(1)?,
                r.get::<_, Option<String>>(2)?,
                r.get::<_, Option<String>>(3)?,
            ))
        })
        .map_err(|e| e.to_string())?;
    let mut grouped: HashMap<(PathBuf, String, String), HashSet<String>> = HashMap::new();
    for row in rows {
        let (id, path_opt, current_name, semantic_name) = row.map_err(|e| e.to_string())?;
        let Some(path_text) = path_opt else { continue };
        let preferred = semantic_name
            .or(current_name)
            .unwrap_or_else(|| "image".into());
        let source = PathBuf::from(&path_text);
        let suffix = source
            .extension()
            .map(|s| format!(".{}", s.to_string_lossy()))
            .unwrap_or_default();
        let target = source.with_file_name(safe_filename(&preferred, &suffix));
        let key = (
            target.parent().map(Path::to_path_buf).unwrap_or_default(),
            target
                .file_stem()
                .map(|s| s.to_string_lossy().to_lowercase())
                .unwrap_or_default(),
            target
                .extension()
                .map(|s| s.to_string_lossy().to_lowercase())
                .unwrap_or_default(),
        );
        grouped.entry(key).or_default().insert(id);
    }
    Ok(grouped)
}

fn plan_semantic_series(
    group: &[(ImageRow, PathBuf)],
    complete_series: bool,
) -> Vec<(String, PathBuf, PathBuf)> {
    let mut ordered: Vec<&(ImageRow, PathBuf)> = group.iter().collect();
    ordered.sort_by(|a, b| {
        race_order_key(&a.0)
            .partial_cmp(&race_order_key(&b.0))
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    if complete_series {
        return plan_complete_semantic_series(&ordered);
    }
    let base_target = ordered[0].1.clone();
    let mut occupied = occupied_series_numbers(&base_target, &HashSet::new());
    let mut planned: Vec<(String, PathBuf, PathBuf)> = Vec::new();
    let mut pending: Vec<(&ImageRow, PathBuf)> = Vec::new();
    for (image, _) in ordered {
        let source = PathBuf::from(&image.current_path);
        match series_number(&source, &base_target) {
            Some(number) => {
                occupied.insert(number);
                planned.push((image.id.clone(), source.clone(), source));
            }
            None => pending.push((image, source)),
        }
    }
    if !pending.is_empty() && occupied.is_empty() {
        if pending.len() == 1 {
            let (image, source) = pending.remove(0);
            occupied.insert(0);
            planned.push((image.id.clone(), source.clone(), base_target.clone()));
        } else {
            for (number, (image, source)) in pending.drain(..).enumerate() {
                let number = (number + 1) as u32;
                occupied.insert(number);
                planned.push((
                    image.id.clone(),
                    source.clone(),
                    indexed_target(&base_target, number),
                ));
            }
        }
    }
    let mut next_number = occupied
        .iter()
        .filter(|&&n| n > 0)
        .max()
        .copied()
        .unwrap_or(0)
        + 1;
    for (image, source) in pending {
        while occupied.contains(&next_number) {
            next_number += 1;
        }
        planned.push((
            image.id.clone(),
            source.clone(),
            indexed_target(&base_target, next_number),
        ));
        occupied.insert(next_number);
        next_number += 1;
    }
    planned
}

fn plan_complete_semantic_series(
    ordered: &[&(ImageRow, PathBuf)],
) -> Vec<(String, PathBuf, PathBuf)> {
    let base_target = ordered[0].1.clone();
    let selected_paths: HashSet<String> = ordered
        .iter()
        .map(|(image, _)| path_key(Path::new(&image.current_path)))
        .collect();
    let blocked = occupied_series_numbers(&base_target, &selected_paths);
    if ordered.len() == 1 && !blocked.contains(&0) {
        let (image, _) = ordered[0];
        return vec![(
            image.id.clone(),
            PathBuf::from(&image.current_path),
            base_target,
        )];
    }
    let mut planned = Vec::new();
    let mut next_number = 1u32;
    for (image, _) in ordered {
        while blocked.contains(&next_number) {
            next_number += 1;
        }
        planned.push((
            image.id.clone(),
            PathBuf::from(&image.current_path),
            indexed_target(&base_target, next_number),
        ));
        next_number += 1;
    }
    planned
}

/// Dry plan: per-file source → target with series numbering, no side effects.
pub fn plan_rename_many(conn: &Connection, ids: &[String]) -> Result<Vec<RenamePlan>, String> {
    let images = load_images(conn, ids)?;
    // Base targets (before series numbering), grouped like Python.
    let mut base: Vec<(ImageRow, PathBuf, String)> = Vec::new();
    for image in images {
        let source = PathBuf::from(&image.current_path);
        let suffix = source
            .extension()
            .map(|s| format!(".{}", s.to_string_lossy()))
            .unwrap_or_default();
        let semantic = safe_filename(&preferred_name(&image), &suffix);
        base.push((image, source.with_file_name(&semantic), semantic));
    }
    let mut grouped: HashMap<SeriesKey, Vec<(ImageRow, PathBuf, String)>> = HashMap::new();
    for (image, target, semantic) in base {
        let key = (
            target.parent().map(Path::to_path_buf).unwrap_or_default(),
            target
                .file_stem()
                .map(|s| s.to_string_lossy().to_string())
                .unwrap_or_default(),
            target
                .extension()
                .map(|s| s.to_string_lossy().to_string())
                .unwrap_or_default(),
        );
        grouped
            .entry(key)
            .or_default()
            .push((image, target, semantic));
    }
    let available = available_semantic_group_ids(conn)?;
    let mut plans = Vec::new();
    // Deterministic group order for stable previews.
    let mut keys: Vec<_> = grouped.keys().cloned().collect();
    keys.sort();
    for key in keys {
        let group = &grouped[&key];
        let selected_ids: HashSet<String> =
            group.iter().map(|(image, _, _)| image.id.clone()).collect();
        let complete_series = selected_ids == *available.get(&key).unwrap_or(&HashSet::new());
        let pairs: Vec<(ImageRow, PathBuf)> = group
            .iter()
            .map(|(image, target, _)| (image.clone(), target.clone()))
            .collect();
        for (image_id, source, target) in plan_semantic_series(&pairs, complete_series) {
            let semantic = target
                .file_name()
                .map(|n| n.to_string_lossy().to_string())
                .unwrap_or_default();
            let would_change = source != target;
            plans.push(RenamePlan {
                image_file_id: image_id,
                source,
                target,
                semantic_name: semantic,
                would_change,
                reason: if would_change {
                    "semantic_name"
                } else {
                    "already_named"
                },
            });
        }
    }
    Ok(plans)
}

/// Preview summary for the confirmation dialog (Python `RenamePlanSummary`
/// parity: total counts the selection, missing counts unknown ids).
pub fn preview_rename(conn: &Connection, ids: &[String]) -> Result<RenamePreview, String> {
    let plans = plan_rename_many(conn, ids)?;
    let planned: HashSet<&str> = plans.iter().map(|p| p.image_file_id.as_str()).collect();
    Ok(RenamePreview {
        total: ids.len(),
        would_change: plans.iter().filter(|p| p.would_change).count(),
        missing: ids
            .iter()
            .filter(|id| !planned.contains(id.as_str()))
            .count(),
        plans,
    })
}

/// Execute rename plans. Missing sources are marked missing in the DB; a
/// target owned by nobody in this batch blocks the whole batch (Python
/// parity) instead of half-renaming; filesystem moves stage through temp
/// names with verify + rollback, then DB paths update.
pub fn rename_files(
    conn: &Connection,
    ids: &[String],
    dry_run: bool,
) -> Result<Vec<RenameOutcome>, String> {
    let plans = plan_rename_many(conn, ids)?;
    if dry_run {
        return Ok(plans
            .into_iter()
            .map(|plan| RenameOutcome {
                plan,
                renamed: false,
                error: None,
            })
            .collect());
    }
    let mut outcomes: HashMap<String, RenameOutcome> = HashMap::new();
    let mut actionable: Vec<RenamePlan> = Vec::new();
    for plan in &plans {
        if !plan.source.exists() {
            let _ = conn.execute(
                "UPDATE image_files SET file_status = 'missing', missing_at = datetime('now') WHERE id = ?1",
                params![plan.image_file_id],
            );
            outcomes.insert(
                plan.image_file_id.clone(),
                RenameOutcome {
                    plan: plan.clone(),
                    renamed: false,
                    error: Some("source file not found".into()),
                },
            );
        } else if !plan.would_change {
            outcomes.insert(
                plan.image_file_id.clone(),
                RenameOutcome {
                    plan: plan.clone(),
                    renamed: false,
                    error: None,
                },
            );
        } else {
            actionable.push(plan.clone());
        }
    }
    if !actionable.is_empty() {
        let source_keys: HashSet<String> = actionable.iter().map(|p| path_key(&p.source)).collect();
        let conflicts: Vec<&RenamePlan> = actionable
            .iter()
            .filter(|p| p.target.exists() && !source_keys.contains(&path_key(&p.target)))
            .collect();
        if !conflicts.is_empty() {
            let names: Vec<String> = conflicts
                .iter()
                .map(|p| {
                    p.target
                        .file_name()
                        .map(|n| n.to_string_lossy().to_string())
                        .unwrap_or_default()
                })
                .collect();
            let error = format!(
                "batch rename blocked by existing target(s): {}",
                names.join(", ")
            );
            for plan in &actionable {
                outcomes.insert(
                    plan.image_file_id.clone(),
                    RenameOutcome {
                        plan: plan.clone(),
                        renamed: false,
                        error: Some(error.clone()),
                    },
                );
            }
        } else if let Some(error) = apply_batch_rename(conn, &actionable) {
            for plan in &actionable {
                outcomes.insert(
                    plan.image_file_id.clone(),
                    RenameOutcome {
                        plan: plan.clone(),
                        renamed: false,
                        error: Some(error.clone()),
                    },
                );
            }
        } else {
            for plan in &actionable {
                outcomes.insert(
                    plan.image_file_id.clone(),
                    RenameOutcome {
                        plan: plan.clone(),
                        renamed: true,
                        error: None,
                    },
                );
            }
        }
    }
    Ok(plans
        .into_iter()
        .map(|plan| {
            outcomes
                .remove(&plan.image_file_id)
                .unwrap_or(RenameOutcome {
                    plan,
                    renamed: false,
                    error: Some("missing_image".into()),
                })
        })
        .collect())
}

fn temporary_rename_path(source: &Path, salt: u128) -> PathBuf {
    let mut candidate = source.with_file_name(format!(
        ".{}.forza-rename-{salt}.tmp",
        source
            .file_name()
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_else(|| "file".into())
    ));
    let mut extra = 0u32;
    while candidate.exists() {
        extra += 1;
        candidate = source.with_file_name(format!(
            ".{}.forza-rename-{salt}-{extra}.tmp",
            source
                .file_name()
                .map(|n| n.to_string_lossy().to_string())
                .unwrap_or_else(|| "file".into())
        ));
    }
    candidate
}

fn apply_batch_rename(conn: &Connection, plans: &[RenamePlan]) -> Option<String> {
    let salt = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let mut staged: Vec<(&RenamePlan, PathBuf)> = Vec::new();
    let mut finalized: Vec<(&RenamePlan, PathBuf)> = Vec::new();
    let mut fail: Option<String> = None;
    for plan in plans {
        let temporary = temporary_rename_path(&plan.source, salt);
        if let Err(e) = std::fs::rename(&plan.source, &temporary) {
            fail = Some(format!("{}: {e}", plan.source.display()));
            break;
        }
        staged.push((plan, temporary));
    }
    if fail.is_none() {
        for (plan, temporary) in &staged {
            match std::fs::rename(temporary, &plan.target).and_then(|_| {
                if plan.target.exists() {
                    Ok(())
                } else {
                    Err(std::io::Error::other(format!(
                        "rename target was not created: {}",
                        plan.target.display()
                    )))
                }
            }) {
                Ok(()) => finalized.push((plan, temporary.clone())),
                Err(e) => {
                    fail = Some(format!("{}: {e}", plan.target.display()));
                    break;
                }
            }
        }
    }
    if fail.is_none() {
        // Verify every target landed before touching the DB.
        let missing: Vec<String> = plans
            .iter()
            .filter(|p| !p.target.exists())
            .map(|p| {
                p.target
                    .file_name()
                    .map(|n| n.to_string_lossy().to_string())
                    .unwrap_or_default()
            })
            .collect();
        if !missing.is_empty() {
            fail = Some(format!(
                "batch rename target(s) missing after filesystem rename: {}",
                missing.join(", ")
            ));
        }
    }
    if let Some(error) = fail {
        // Roll back: finalized targets back to temp, temps back to sources.
        let mut rollback_errors = Vec::new();
        for (plan, temporary) in finalized.iter().rev() {
            if plan.target.exists()
                && let Err(e) = std::fs::rename(&plan.target, temporary)
            {
                rollback_errors.push(format!("{}: {e}", plan.target.display()));
            }
        }
        for (plan, temporary) in staged.iter().rev() {
            if temporary.exists()
                && let Err(e) = std::fs::rename(temporary, &plan.source)
            {
                rollback_errors.push(format!("{}: {e}", temporary.display()));
            }
        }
        for (plan, temporary) in &staged {
            if !plan.source.exists() {
                rollback_errors.push(format!(
                    "{}: rollback did not restore source",
                    plan.source.display()
                ));
            }
            if temporary.exists() {
                rollback_errors.push(format!(
                    "{}: rollback temporary remains",
                    temporary.display()
                ));
            }
        }
        let detail = if rollback_errors.is_empty() {
            String::new()
        } else {
            format!("; rollback errors: {}", rollback_errors.join(", "))
        };
        return Some(format!("{error}{detail}"));
    }
    // All files moved and verified: update DB paths in one go.
    for plan in plans {
        let name = plan
            .target
            .file_name()
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_default();
        if let Err(e) = conn.execute(
            "UPDATE image_files SET current_path = ?2, current_name = ?3,
                    file_status = 'available', missing_at = NULL, updated_at = datetime('now')
             WHERE id = ?1",
            params![plan.image_file_id, plan.target.to_string_lossy(), name],
        ) {
            // DB failed after verified moves: roll files back like above.
            let _ = std::fs::rename(&plan.target, &plan.source);
            return Some(format!("DB update failed for {}: {e}", plan.image_file_id));
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    fn numbered(path: &Path, base: &Path) -> Option<u32> {
        series_number(path, base)
    }

    #[test]
    fn series_numbers_match_python_rules() {
        let base = Path::new("C:/shots/Fuji Speedway - A.png");
        assert_eq!(
            numbered(Path::new("C:/shots/Fuji Speedway - A.png"), base),
            Some(0)
        );
        assert_eq!(
            numbered(Path::new("C:/shots/FUJI SPEEDWAY - A.png"), base),
            Some(0),
            "stem match is case-insensitive (parent stays exact, like Python)"
        );
        assert_eq!(
            numbered(Path::new("C:/shots/Fuji Speedway - A - Race 007.png"), base),
            Some(7)
        );
        assert_eq!(numbered(Path::new("C:/shots/Other - A.png"), base), None);
        assert_eq!(
            numbered(Path::new("C:/shots/Fuji Speedway - A - Race x.png"), base),
            None
        );
        assert_eq!(
            numbered(Path::new("C:/shots/Fuji Speedway - A.jpg"), base),
            None,
            "suffix must match"
        );
    }

    #[test]
    fn safe_filename_blocks_reserved_and_forbidden() {
        assert_eq!(safe_filename("CON", ".png"), "CON_.png");
        assert_eq!(safe_filename("a<b", ".png"), "ab.png");
        assert_eq!(safe_filename("", ".png"), "image.png");
    }

    #[test]
    fn batch_plans_series_numbers_for_repeated_names() {
        let dir = tempfile::tempdir().unwrap();
        let db = dir.path().join("rename.sqlite3");
        forza_db::upgrade(&db).unwrap();
        let conn = forza_db::open_connection(&db).unwrap();
        for (id, name) in [("i1", "a.png"), ("i2", "b.png"), ("i3", "c.png")] {
            let path = dir.path().join(name);
            std::fs::write(&path, "x").unwrap();
            conn.execute(
                "INSERT INTO image_files
                    (id, file_hash, current_name, current_path, semantic_name,
                     file_status, first_seen_at, created_at, updated_at)
                 VALUES (?1, ?2, ?3, ?4, 'Fuji Speedway - A.png', 'available',
                         datetime('now'), datetime('now'), datetime('now'))",
                params![id, format!("h-{id}"), name, path.to_string_lossy()],
            )
            .unwrap();
        }
        let plans = plan_rename_many(
            &conn,
            &["i1".to_string(), "i2".to_string(), "i3".to_string()],
        )
        .unwrap();
        assert_eq!(plans.len(), 3);
        // Complete series of 3 sharing one semantic name: numbered from 1.
        let mut targets: Vec<String> = plans
            .iter()
            .map(|p| p.target.file_name().unwrap().to_string_lossy().to_string())
            .collect();
        targets.sort();
        assert_eq!(
            targets,
            vec![
                "Fuji Speedway - A - Race 001.png",
                "Fuji Speedway - A - Race 002.png",
                "Fuji Speedway - A - Race 003.png",
            ]
        );
        assert!(plans.iter().all(|p| p.would_change));
    }
}
