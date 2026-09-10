//! Shared CLI helpers: path resolution, config loading, display.

use std::path::{Path, PathBuf};

use rusqlite::Connection;

fn resolve_db_path(config_path: &Path, configured: PathBuf) -> PathBuf {
    if configured.is_absolute() {
        return configured;
    }
    match config_path.parent() {
        Some(parent) if !parent.as_os_str().is_empty() => parent.join(configured),
        _ => configured,
    }
}

pub(crate) fn database_file(config_path: &Path) -> PathBuf {
    match forza_config::load_config(config_path, false) {
        Ok((cfg, _)) => resolve_db_path(config_path, cfg.database_file),
        Err(_) => PathBuf::from("data/forza.sqlite3"),
    }
}

/// Short display identity for dry-run listings. Never panics on short or
/// legacy hashes (test seeds use `"abc123"`).
pub(crate) fn short_hash(hash: &str) -> &str {
    hash.get(..12).unwrap_or(hash)
}

/// conflate corruption with "empty" — callers print ERR instead of 0).
pub(crate) fn table_count(conn: &Connection, name: &str) -> Option<i64> {
    conn.query_row(&format!("SELECT COUNT(*) FROM \"{name}\""), [], |r| {
        r.get(0)
    })
    .ok()
}

/// Lenient load + print warnings, then enforce `validate_config`: run /
/// rebuild / export must not proceed with `workers=0`, `image_format=bmp`
/// etc. into obscure downstream failures when `config-check` already fails.
pub(crate) fn load_validated_config(
    config_path: &Path,
    strict: bool,
) -> anyhow::Result<forza_config::AppConfig> {
    let (cfg, warnings) = forza_config::load_config(config_path, strict)?;
    for warning in &warnings {
        eprintln!("warning: {warning}");
    }
    match forza_config::validate_config(&cfg) {
        Ok(()) => Ok(cfg),
        Err(errors) => Err(anyhow::anyhow!(
            "configuration invalid (run `forza config-check`): {}",
            errors.join("; ")
        )),
    }
}

#[cfg(test)]
#[allow(clippy::unwrap_used)]
mod tests {
    use super::*;

    #[test]
    fn short_hash_never_panics() {
        assert_eq!(short_hash("abc123"), "abc123");
        assert_eq!(short_hash(""), "");
        assert_eq!(short_hash("deadbeefcafe1234567890_extra"), "deadbeefcafe");
    }

    #[test]
    fn resolve_db_path_prefers_config_dir_over_cwd() {
        // Absolute configured path wins as-is.
        assert_eq!(
            resolve_db_path(
                Path::new("/other/dir/forza_config.ini"),
                PathBuf::from("/abs/data.sqlite3")
            ),
            PathBuf::from("/abs/data.sqlite3")
        );
        // Bare relative resolves against the config directory, not CWD.
        assert_eq!(
            resolve_db_path(
                Path::new("/other/dir/forza_config.ini"),
                PathBuf::from("data/forza.sqlite3")
            ),
            PathBuf::from("/other/dir/data/forza.sqlite3")
        );
        // Bare config filename has no parent: relative stays relative.
        assert_eq!(
            resolve_db_path(
                Path::new("forza_config.ini"),
                PathBuf::from("data/forza.sqlite3")
            ),
            PathBuf::from("data/forza.sqlite3")
        );
    }

    #[test]
    fn database_file_falls_back_without_panicking_on_missing_config() {
        let dir = std::env::temp_dir().join("forza-cli-test-missing");
        let missing = dir.join("definitely_missing_8f3a.ini");
        let _ = std::fs::remove_file(&missing);
        // Missing config resolves to defaults, never panics.
        let db = database_file(&missing);
        assert!(!db.as_os_str().is_empty());
    }
}
