//! File logging for extraction runs (parity with Python `logging_setup`).
//!
//! Run events previously lived only in memory (GUI log panel / CLI stdout),
//! so `cfg.log_file` stayed empty forever and the GUI Logs page showed
//! "Log file not found". Front-ends pass their already-formatted lines here;
//! this module owns file mechanics only (parent dirs, timestamps, append).

use std::path::{Path, PathBuf};

/// `<stem>_errors<suffix>` sibling of the main log, mirroring the GUI worker's
/// errors-log convention (it should import this instead of duplicating it).
pub fn errors_log_path(log_file: &Path) -> PathBuf {
    let stem = log_file
        .file_stem()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_else(|| "forza".into());
    let suffix = log_file
        .extension()
        .map(|e| format!(".{}", e.to_string_lossy()))
        .unwrap_or_default();
    log_file
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join(format!("{stem}_errors{suffix}"))
}

fn timestamp() -> String {
    chrono::Local::now().format("%Y-%m-%d %H:%M:%S").to_string()
}

/// Append one `[timestamp] line` record, creating parent directories.
/// Best-effort by design: logging must never fail a run.
pub fn append_log_file(log_file: &Path, line: &str) {
    if log_file.as_os_str().is_empty() {
        return;
    }
    if let Some(parent) = log_file.parent()
        && !parent.as_os_str().is_empty()
    {
        let _ = std::fs::create_dir_all(parent);
    }
    use std::io::Write as _;
    if let Ok(mut file) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_file)
    {
        let _ = writeln!(file, "[{}] {line}", timestamp());
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn errors_path_derives_from_stem() {
        assert_eq!(
            errors_log_path(Path::new("logs/forza_debug.log")),
            PathBuf::from("logs/forza_debug_errors.log")
        );
        assert_eq!(
            errors_log_path(Path::new("forza.log")),
            PathBuf::from("forza_errors.log")
        );
    }

    #[test]
    fn append_creates_parent_dirs_and_prefixes_timestamp() {
        let dir = tempfile::tempdir().unwrap();
        let target = dir.path().join("nested").join("run.log");
        append_log_file(&target, "hello");
        append_log_file(&target, "world");
        let content = std::fs::read_to_string(&target).unwrap();
        let lines: Vec<&str> = content.lines().collect();
        assert_eq!(lines.len(), 2);
        assert!(lines[0].ends_with("hello"));
        assert!(lines[1].ends_with("world"));
        assert!(lines[0].starts_with('['));
        // Empty path is a silent no-op, never an error.
        append_log_file(Path::new(""), "dropped");
    }
}
