// Path resolution contract: relative [paths] entries resolve against the
// INI file's directory so every front-end agrees on which files a config
// means regardless of the process working directory.
// Test harness code: unwraps are the idiomatic assertion helpers here.
#![allow(clippy::unwrap_used)]

use forza_config::{load_config, resolve_path, resolve_paths};
use std::path::{Path, PathBuf};

#[test]
fn relative_paths_resolve_against_ini_dir() {
    let ini = Path::new("/bundle/forza_config.ini");
    assert_eq!(
        resolve_path(ini, Path::new("data/forza.sqlite3")),
        PathBuf::from("/bundle/data/forza.sqlite3")
    );
    assert_eq!(
        resolve_path(ini, Path::new("data/input")),
        PathBuf::from("/bundle/data/input")
    );
}

#[test]
fn absolute_paths_pass_through() {
    let ini = Path::new("/bundle/forza_config.ini");
    let abs = Path::new("/elsewhere/db.sqlite3");
    assert_eq!(resolve_path(ini, abs), abs.to_path_buf());
}

#[test]
fn bare_filename_without_parent_resolves_as_is() {
    // `forza_config.ini` in the cwd: no parent to join against.
    let ini = Path::new("forza_config.ini");
    let rel = Path::new("data/forza.sqlite3");
    assert_eq!(resolve_path(ini, rel), rel.to_path_buf());
}

#[test]
fn resolve_paths_rewrites_all_four_path_entries() {
    let dir = tempfile::tempdir().unwrap();
    let ini_path = dir.path().join("sub").join("forza_config.ini");
    std::fs::create_dir_all(ini_path.parent().unwrap()).unwrap();
    std::fs::write(
        &ini_path,
        "[paths]\ninput_dir = data/input\npdf_file = out/r.pdf\nlog_file = logs/a.log\ndatabase_file = data/f.sqlite3\n[user]\ngamertag = T\n",
    )
    .unwrap();
    let (mut cfg, _) = load_config(&ini_path, false).unwrap();
    resolve_paths(&ini_path, &mut cfg);
    let sub = ini_path.parent().unwrap();
    assert_eq!(cfg.input_dir, sub.join("data/input"));
    assert_eq!(cfg.pdf_file, sub.join("out/r.pdf"));
    assert_eq!(cfg.log_file, sub.join("logs/a.log"));
    assert_eq!(cfg.database_file, sub.join("data/f.sqlite3"));
}
