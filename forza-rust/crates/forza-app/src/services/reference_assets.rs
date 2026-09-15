//! Sync of operator-confirmed cars into the shipped `cars.txt` assets.
//!
//! The database catalog (`reference_cars`) is the runtime source of truth —
//! `known_cars()` unions embedded assets with it, so a confirmed car takes
//! effect immediately. This module covers the remaining gap: without it, a
//! regenerated database redetects the same cars as novel. Sync is
//! best-effort and never fails a decision: the DB already holds the data,
//! the asset file is a convenience for fresh databases and future builds
//! (which embed it at compile time).

use std::path::{Path, PathBuf};

/// Asset files updated when resolvable: the embedded source and its legacy
/// repo-root twin (kept byte-identical by convention).
fn candidate_asset_paths_from(exe_dir: &Path) -> Vec<PathBuf> {
    vec![
        exe_dir.join("../../assets/cars.txt"),
        exe_dir.join("../../../cars.txt"),
    ]
}

/// Candidate asset paths resolved from the running executable's directory.
pub fn candidate_asset_paths() -> Vec<PathBuf> {
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(Path::to_path_buf))
        .unwrap_or_default();
    candidate_asset_paths_from(&exe_dir)
}

/// Insert `car` into the asset file at `path` in case-insensitive sorted
/// order (the file convention), skipping case-insensitive duplicates.
/// Only touches files that already exist — never creates directories.
/// Returns `true` when the file changed.
pub fn sync_car_to_asset_file(path: &Path, car: &str) -> Result<bool, String> {
    let clean = car.trim();
    if clean.is_empty() || clean.contains(['\n', '\r']) {
        return Ok(false);
    }
    if !path.is_file() {
        return Ok(false);
    }
    let text = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let mut lines: Vec<String> = text.lines().map(str::to_string).collect();
    if lines
        .iter()
        .any(|l| l.trim().to_lowercase() == clean.to_lowercase())
    {
        return Ok(false);
    }
    let pos = lines
        .iter()
        .position(|l| l.to_lowercase() > clean.to_lowercase())
        .unwrap_or(lines.len());
    lines.insert(pos, clean.to_string());
    let mut out = lines.join("\n");
    out.push('\n');
    std::fs::write(path, out).map_err(|e| e.to_string())?;
    Ok(true)
}

/// Best-effort sync of a confirmed-novel car into every resolvable asset
/// file. Returns the number of files updated; failures are swallowed by
/// design (see module docs).
pub fn sync_confirmed_car(car: &str) -> usize {
    sync_confirmed_car_to(&candidate_asset_paths(), car)
}

fn sync_confirmed_car_to(paths: &[PathBuf], car: &str) -> usize {
    paths
        .iter()
        .filter(|p| sync_car_to_asset_file(p, car).unwrap_or(false))
        .count()
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;

    fn fixture(content: &str) -> (tempfile::TempDir, PathBuf) {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("cars.txt");
        std::fs::write(&path, content).unwrap();
        (dir, path)
    }

    #[test]
    fn inserts_in_sorted_position() {
        let (_d, path) = fixture("Audi R8 '16\nBMW M4 '14\n");
        assert!(sync_car_to_asset_file(&path, "Bentley #17 C").unwrap());
        assert_eq!(
            std::fs::read_to_string(&path).unwrap(),
            "Audi R8 '16\nBentley #17 C\nBMW M4 '14\n"
        );
    }

    #[test]
    fn skips_duplicates_case_insensitively_and_blank_values() {
        let (_d, path) = fixture("Audi R8 '16\n");
        assert!(!sync_car_to_asset_file(&path, "audi r8 '16").unwrap());
        assert!(!sync_car_to_asset_file(&path, "  ").unwrap());
        assert!(!sync_car_to_asset_file(&path, "a\nb").unwrap());
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "Audi R8 '16\n");
    }

    #[test]
    fn missing_file_is_a_no_op_not_an_error() {
        let dir = tempfile::tempdir().unwrap();
        assert!(!sync_car_to_asset_file(&dir.path().join("nope.txt"), "X").unwrap());
    }

    #[test]
    fn sync_to_paths_updates_each_existing_file_once() {
        let (_d1, p1) = fixture("B\n");
        let (_d2, p2) = fixture("B\n");
        let missing = p1.parent().unwrap().join("missing.txt");
        let paths = vec![p1.clone(), p2.clone(), missing];
        assert_eq!(sync_confirmed_car_to(&paths, "A"), 2);
        assert_eq!(sync_confirmed_car_to(&paths, "A"), 0);
        for p in [p1, p2] {
            assert_eq!(std::fs::read_to_string(&p).unwrap(), "A\nB\n");
        }
    }

    #[test]
    fn candidate_paths_cover_embedded_and_root_assets() {
        let exe = Path::new("/ws/forza-rust/target/release");
        let cands = candidate_asset_paths_from(exe);
        assert_eq!(
            cands,
            vec![
                PathBuf::from("/ws/forza-rust/target/release/../../assets/cars.txt"),
                PathBuf::from("/ws/forza-rust/target/release/../../../cars.txt"),
            ]
        );
    }
}
