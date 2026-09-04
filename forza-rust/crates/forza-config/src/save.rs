//! Safe writer for `forza_config.ini` — port of the Python
//! `ConfigFileService` contract (application/config_service.py).
//!
//! Flow: load strict from disk → apply string changes onto a candidate
//! [`AppConfig`] → `validate_config` → timestamped backup → ordered INI write
//! (tmp + atomic replace). Unknown sections/keys are preserved; obsolete keys
//! are pruned exactly like the Python writer.

use std::path::{Path, PathBuf};

use crate::ini::IniDocument;
use crate::{AppConfig, load_config, validate_config};

/// Result of a successful save.
#[derive(Debug, Clone, PartialEq)]
pub struct SaveOutcome {
    pub message: String,
    pub backup_path: Option<PathBuf>,
    /// True when the change set touched `user.gamertag` (frontier identity),
    /// so callers can trigger the best-lap recompute contract.
    pub gamertag_changed: bool,
    /// The configuration as re-read from disk after the save.
    pub config: AppConfig,
}

const EDITABLE_PATHS: &[&str] = &["input_dir", "pdf_file", "log_file", "database_file"];

/// Build the candidate configuration that would result from applying
/// `changes` to the current file. Fails with the exact operator-facing
/// message when any value cannot be applied or fails validation.
pub fn candidate_config(
    path: &Path,
    changes: &std::collections::BTreeMap<String, String>,
) -> Result<AppConfig, String> {
    // Load leniently: a stale invalid value in an unrelated field must not
    // block saving a valid edit. The candidate as a whole is still validated
    // below, so nothing invalid can be written.
    let (base, _) = load_config(path, false).map_err(|e| e.message)?;
    let mut candidate = base;
    // BTreeMap iterates sorted; Python applies in dict insertion order, which
    // for the GUI's single-edit flow is equivalent.
    for (field, raw_value) in changes {
        apply_field(&mut candidate, field, raw_value.trim())?;
    }
    validate_messages(&candidate)?;
    Ok(candidate)
}

/// Validate what a change set would produce without writing anything.
/// Returns the success message on validity.
pub fn validate_changes(
    path: &Path,
    changes: &std::collections::BTreeMap<String, String>,
) -> Result<String, String> {
    if changes.is_empty() {
        return Ok("Configuration is valid for execution.".to_string());
    }
    candidate_config(path, changes)?;
    Ok("Configuration is valid for execution.".to_string())
}

/// Apply changes, back up the current file and write the new one atomically.
pub fn save_changes(
    path: &Path,
    changes: &std::collections::BTreeMap<String, String>,
) -> Result<SaveOutcome, String> {
    if changes.is_empty() {
        return Err("No changes to save.".to_string());
    }
    let previous = load_config(path, false).map_err(|e| e.message)?.0;
    let candidate = candidate_config(path, changes)?;
    let backup_path = backup(path)?;
    write_candidate(path, &candidate)?;
    let (config, _) = load_config(path, false).map_err(|e| e.message)?;
    Ok(SaveOutcome {
        message: match &backup_path {
            Some(backup) => format!("Configuration saved. Backup: {}", backup.display()),
            None => "Configuration saved.".to_string(),
        },
        backup_path,
        gamertag_changed: changes.contains_key("user.gamertag")
            && previous.gamertag != config.gamertag,
        config,
    })
}

fn validate_messages(cfg: &AppConfig) -> Result<(), String> {
    match validate_config(cfg) {
        Ok(()) => Ok(()),
        Err(errors) => Err(format_validation_errors(&errors)),
    }
}

/// Python `str(ConfigValidationError)` layout: a header followed by bulleted
/// failures, so operators can fix everything in one pass.
pub fn format_validation_errors(errors: &[String]) -> String {
    let mut message = String::from("Configuration errors:");
    for error in errors {
        message.push_str("\n  \u{2022} ");
        message.push_str(error);
    }
    message
}

fn apply_field(cfg: &mut AppConfig, field: &str, value: &str) -> Result<(), String> {
    if let Some(key) = field.strip_prefix("paths.") {
        return apply_path(cfg, key, value);
    }
    if let Some(key) = field.strip_prefix("llm.") {
        return apply_llm(cfg, key, value);
    }
    if let Some(key) = field.strip_prefix("image.") {
        return apply_image(cfg, key, value);
    }
    if let Some(key) = field.strip_prefix("validation.") {
        return apply_validation(cfg, key, value);
    }
    if let Some(key) = field.strip_prefix("pdf.") {
        return apply_pdf(cfg, key, value);
    }
    if let Some(key) = field.strip_prefix("ui.") {
        return apply_ui(cfg, key, value);
    }
    if field == "prompt.active" {
        cfg.prompt.active = value.to_string();
        return Ok(());
    }
    if field == "user.gamertag" {
        cfg.gamertag = value.to_string();
        return Ok(());
    }
    Err(format!("Field is not editable: {field}"))
}

fn apply_path(cfg: &mut AppConfig, key: &str, value: &str) -> Result<(), String> {
    if !EDITABLE_PATHS.contains(&key) {
        return Err(format!("Field is not editable: paths.{key}"));
    }
    if value.is_empty() {
        return Err(format!("[paths] {key} cannot be empty"));
    }
    let path = PathBuf::from(value);
    match key {
        "input_dir" => cfg.input_dir = path,
        "pdf_file" => cfg.pdf_file = path,
        "log_file" => cfg.log_file = path,
        "database_file" => cfg.database_file = path,
        _ => unreachable!("guarded by EDITABLE_PATHS"),
    }
    Ok(())
}

fn apply_llm(cfg: &mut AppConfig, key: &str, value: &str) -> Result<(), String> {
    let llm = &mut cfg.llm;
    match key {
        "workers" => cfg.workers = parse_int(value)?,
        "max_completion_tokens" => llm.max_completion_tokens = parse_int(value)?,
        "timeout_connect" => llm.timeout_connect = parse_int(value)?,
        "timeout_read" => llm.timeout_read = parse_int(value)?,
        "max_retries" => llm.max_retries = parse_int(value)?,
        "performance_reload_streak" => llm.performance_reload_streak = parse_int(value)?,
        "eval_batch_size" => llm.eval_batch_size = parse_opt_int(value)?,
        "physical_batch_size" => llm.physical_batch_size = parse_opt_int(value)?,
        "context_length" => llm.context_length = parse_opt_int(value)?,
        "temperature" => llm.temperature = parse_float(value)?,
        "performance_tps_floor" => llm.performance_tps_floor = parse_float(value)?,
        "performance_reload_elapsed_s" => llm.performance_reload_elapsed_s = parse_float(value)?,
        "flash_attention" => llm.flash_attention = parse_bool(value)?,
        "offload_kv_cache_to_gpu" => llm.offload_kv_cache_to_gpu = parse_bool(value)?,
        "url" => llm.url = value.to_string(),
        "model" => llm.model = value.to_string(),
        "image_format" => llm.image_format = value.to_string(),
        "reasoning_mode" => {
            let v = value.trim().to_lowercase();
            llm.reasoning_mode = (!v.is_empty()).then_some(v);
        }
        other => return Err(format!("Unknown LLM field: {other}")),
    }
    Ok(())
}

fn apply_image(cfg: &mut AppConfig, key: &str, value: &str) -> Result<(), String> {
    match key {
        "max_width" => cfg.image.max_width = parse_int(value)?,
        "encode_quality" => cfg.image.encode_quality = parse_int(value)?,
        "grayscale" => cfg.image.grayscale = parse_bool(value)?,
        other => return Err(format!("Unknown image field: {other}")),
    }
    Ok(())
}

fn apply_validation(cfg: &mut AppConfig, key: &str, value: &str) -> Result<(), String> {
    match key {
        "temp_min_f" => cfg.validation.temp_min_f = parse_float(value)?,
        "temp_max_f" => cfg.validation.temp_max_f = parse_float(value)?,
        other => return Err(format!("Unknown validation field: {other}")),
    }
    Ok(())
}

fn apply_pdf(cfg: &mut AppConfig, key: &str, value: &str) -> Result<(), String> {
    match key {
        "dirty_lap_symbol" => cfg.pdf.dirty_lap_symbol = value.to_string(),
        "show_dirty_lap_symbol" => cfg.pdf.show_dirty_lap_symbol = parse_bool(value)?,
        other => return Err(format!("Unknown PDF field: {other}")),
    }
    Ok(())
}

fn apply_ui(cfg: &mut AppConfig, key: &str, value: &str) -> Result<(), String> {
    match key {
        "font_scale" => cfg.ui.font_scale = parse_float(value)?,
        "min_font_px" => cfg.ui.min_font_px = parse_int(value)?,
        other => return Err(format!("Unknown ui field: {other}")),
    }
    Ok(())
}

fn parse_int(value: &str) -> Result<i64, String> {
    value
        .parse::<i64>()
        .map_err(|e| format!("invalid literal for int() with base 10: '{value}' ({e})"))
}

fn parse_opt_int(value: &str) -> Result<Option<i64>, String> {
    if value.is_empty() {
        return Ok(None);
    }
    parse_int(value).map(|parsed| (parsed != 0).then_some(parsed))
}

fn parse_float(value: &str) -> Result<f64, String> {
    value
        .parse::<f64>()
        .map_err(|e| format!("could not convert string to float: '{value}' ({e})"))
}

fn parse_bool(value: &str) -> Result<bool, String> {
    match value.trim().to_lowercase().as_str() {
        "1" | "true" | "yes" | "y" | "on" => Ok(true),
        "0" | "false" | "no" | "n" | "off" => Ok(false),
        _ => Err(format!("Invalid boolean value: {value}")),
    }
}

/// Timestamped `.bak` copy (`name.YYYYmmdd-HHMMSS-ffffff.bak`), with a counter
/// suffix when two saves land inside the same microsecond stamp.
fn backup(config_path: &Path) -> Result<Option<PathBuf>, String> {
    if !config_path.exists() {
        return Ok(None);
    }
    let stamp = local_timestamp_micros();
    let file_name = config_path
        .file_name()
        .ok_or_else(|| "config path has no file name".to_string())?
        .to_string_lossy()
        .to_string();
    let mut backup_path = config_path.with_file_name(format!("{file_name}.{stamp}.bak"));
    let mut counter = 2;
    while backup_path.exists() {
        backup_path = config_path.with_file_name(format!("{file_name}.{stamp}-{counter}.bak"));
        counter += 1;
    }
    std::fs::copy(config_path, &backup_path).map_err(|e| format!("backup failed: {e}"))?;
    Ok(Some(backup_path))
}

fn write_candidate(config_path: &Path, cfg: &AppConfig) -> Result<(), String> {
    let existing = std::fs::read_to_string(config_path).unwrap_or_default();
    let mut doc = IniDocument::parse(&existing);

    doc.ensure_section("paths");
    doc.set("paths", "input_dir", &cfg.input_dir.to_string_lossy());
    doc.set("paths", "pdf_file", &cfg.pdf_file.to_string_lossy());
    doc.set("paths", "log_file", &cfg.log_file.to_string_lossy());
    doc.set(
        "paths",
        "database_file",
        &cfg.database_file.to_string_lossy(),
    );
    for obsolete in [
        "tracks_file",
        "cars_file",
        "output_dir",
        "benchmark_file",
        "raw_artifacts_dir",
        "raw_dir",
        "calibration_samples_dir",
        "external_records_file",
        "review_dir",
        "corrections_dir",
        "manual_overrides_file",
    ] {
        doc.remove_key("paths", obsolete);
    }

    doc.set("user", "gamertag", &cfg.gamertag);

    doc.set("llm", "workers", &cfg.workers.to_string());
    for obsolete in ["backend", "max_workers", "worker_mode"] {
        doc.remove_key("llm", obsolete);
    }

    let llm = &cfg.llm;
    doc.set("lmstudio", "url", &llm.url);
    doc.set("lmstudio", "model", &llm.model);
    doc.set(
        "lmstudio",
        "max_completion_tokens",
        &llm.max_completion_tokens.to_string(),
    );
    doc.set("lmstudio", "temperature", &py_float(llm.temperature));
    doc.set(
        "lmstudio",
        "timeout_connect",
        &llm.timeout_connect.to_string(),
    );
    doc.set("lmstudio", "timeout_read", &llm.timeout_read.to_string());
    doc.set("lmstudio", "max_retries", &llm.max_retries.to_string());
    doc.set("lmstudio", "image_format", &llm.image_format);
    doc.set("lmstudio", "context_length", &opt_str(llm.context_length));
    doc.set(
        "lmstudio",
        "reasoning_mode",
        llm.reasoning_mode.as_deref().unwrap_or(""),
    );
    doc.set("lmstudio", "eval_batch_size", &opt_str(llm.eval_batch_size));
    doc.set(
        "lmstudio",
        "physical_batch_size",
        &opt_str(llm.physical_batch_size),
    );
    doc.set("lmstudio", "flash_attention", py_bool(llm.flash_attention));
    doc.set(
        "lmstudio",
        "offload_kv_cache_to_gpu",
        py_bool(llm.offload_kv_cache_to_gpu),
    );
    doc.set(
        "lmstudio",
        "performance_tps_floor",
        &py_float(llm.performance_tps_floor),
    );
    doc.set(
        "lmstudio",
        "performance_reload_elapsed_s",
        &py_float(llm.performance_reload_elapsed_s),
    );
    doc.set(
        "lmstudio",
        "performance_reload_streak",
        &llm.performance_reload_streak.to_string(),
    );
    for obsolete in ["api_family", "max_parse_retries"] {
        doc.remove_key("lmstudio", obsolete);
    }
    doc.remove_section("ollama");

    doc.set("image", "max_width", &cfg.image.max_width.to_string());
    doc.set(
        "image",
        "encode_quality",
        &cfg.image.encode_quality.to_string(),
    );
    doc.set("image", "grayscale", py_bool(cfg.image.grayscale));

    doc.set(
        "validation",
        "temp_min_f",
        &py_float(cfg.validation.temp_min_f),
    );
    doc.set(
        "validation",
        "temp_max_f",
        &py_float(cfg.validation.temp_max_f),
    );

    doc.set("pdf", "dirty_lap_symbol", &cfg.pdf.dirty_lap_symbol);
    doc.set(
        "pdf",
        "show_dirty_lap_symbol",
        py_bool(cfg.pdf.show_dirty_lap_symbol),
    );

    doc.set("prompt", "active", &cfg.prompt.active);

    doc.set("ui", "font_scale", &py_float(cfg.ui.font_scale));
    doc.set("ui", "min_font_px", &cfg.ui.min_font_px.to_string());

    if let Some(parent) = config_path.parent()
        && !parent.as_os_str().is_empty()
    {
        std::fs::create_dir_all(parent).map_err(|e| format!("mkdir failed: {e}"))?;
    }
    let tmp_path = config_path.with_file_name(format!(
        "{}.tmp",
        config_path
            .file_name()
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_default()
    ));
    std::fs::write(&tmp_path, doc.render()).map_err(|e| format!("write failed: {e}"))?;
    std::fs::rename(&tmp_path, config_path).map_err(|e| format!("replace failed: {e}"))
}

fn opt_str(value: Option<i64>) -> String {
    match value {
        None => String::new(),
        Some(v) => v.to_string(),
    }
}

fn py_bool(value: bool) -> &'static str {
    if value { "True" } else { "False" }
}

/// Python `str(float)` formatting: always shows a decimal part ("45.0").
/// Rust's Debug formatter for f64 matches repr for common magnitudes.
fn py_float(value: f64) -> String {
    format!("{value:?}")
}

/// `%Y%m%d-%H%M%S-%f` in local time approximated by UTC offset-free wall clock
/// (the stamp only needs uniqueness and human ordering, not timezone truth).
fn local_timestamp_micros() -> String {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default();
    let secs = now.as_secs() as i64;
    let micros = now.subsec_micros();
    let days = secs.div_euclid(86_400);
    let seconds_of_day = secs.rem_euclid(86_400);
    let (year, month, day) = civil_from_days(days);
    format!(
        "{year:04}{month:02}{day:02}-{h:02}{m:02}{s:02}-{micros:06}",
        h = seconds_of_day / 3600,
        m = (seconds_of_day % 3600) / 60,
        s = seconds_of_day % 60,
    )
}

/// Howard Hinnant's civil-from-days algorithm.
fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    ((if m <= 2 { y + 1 } else { y }), m, d)
}

#[cfg(test)]
mod tests {
    use super::*;

    const BASE_INI: &str = "[paths]\ninput_dir = data/input\npdf_file = output/reports/forza_bestlaps.pdf\nlog_file = output/logs/forza_debug.log\ndatabase_file = data/forza.sqlite3\noutput_dir = x\n\n[user]\ngamertag = Player\n\n[llm]\nworkers = 1\nbackend = old\n\n[lmstudio]\nurl = http://127.0.0.1:1234/api/v1/chat\nmodel = qwen/test\ntemperature = 0.0\ncontext_length = 5000\nreasoning_mode = off\neval_batch_size = 1024\nflash_attention = True\n\n[prompt]\nactive = user_header_shaped_v1\n";

    fn write_base(dir: &Path) -> PathBuf {
        let path = dir.join("forza_config.ini");
        std::fs::write(&path, BASE_INI).unwrap();
        path
    }

    fn map(pairs: &[(&str, &str)]) -> std::collections::BTreeMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    }

    #[test]
    fn save_applies_values_and_prunes_obsolete_keys() {
        let dir = tempfile::tempdir().unwrap();
        let path = write_base(dir.path());

        let outcome = save_changes(
            &path,
            &map(&[("user.gamertag", "Bujica89"), ("llm.workers", "2")]),
        )
        .unwrap();

        assert!(outcome.gamertag_changed);
        assert_eq!(outcome.config.gamertag, "Bujica89");
        assert_eq!(outcome.config.workers, 2);
        assert!(outcome.backup_path.is_some());

        let text = std::fs::read_to_string(&path).unwrap();
        assert!(text.contains("gamertag = Bujica89"));
        assert!(text.contains("workers = 2"));
        assert!(!text.contains("output_dir"), "obsolete paths key pruned");
        assert!(!text.contains("backend"), "obsolete llm key pruned");
        assert!(text.contains("[prompt]"), "sections preserved");
        assert!(text.contains("temperature = 0.0"), "python float repr");
        assert!(text.contains("flash_attention = True"), "capitalized bool");
    }

    #[test]
    fn save_rejects_invalid_value_without_touching_file() {
        let dir = tempfile::tempdir().unwrap();
        let path = write_base(dir.path());
        let before = std::fs::read_to_string(&path).unwrap();

        let error = save_changes(&path, &map(&[("image.encode_quality", "999")])).unwrap_err();

        assert!(
            error.contains("encode_quality"),
            "validation message: {error}"
        );
        assert_eq!(before, std::fs::read_to_string(&path).unwrap());
    }

    #[test]
    fn preview_reports_valid_and_invalid_changes() {
        let dir = tempfile::tempdir().unwrap();
        let path = write_base(dir.path());

        let ok = validate_changes(&path, &map(&[("llm.temperature", "0.5")]));
        assert!(ok.is_ok());

        let bad = validate_changes(&path, &map(&[("image.max_width", "10")]));
        assert!(bad.is_err());
        assert!(bad.unwrap_err().starts_with("Configuration errors:"));
    }

    #[test]
    fn empty_and_unknown_fields_behave_like_python() {
        let dir = tempfile::tempdir().unwrap();
        let path = write_base(dir.path());

        assert_eq!(
            save_changes(&path, &map(&[])).unwrap_err(),
            "No changes to save."
        );
        assert_eq!(
            apply_field_error(&path, "prompt.other", "x"),
            "Field is not editable: prompt.other"
        );
        assert_eq!(
            apply_field_error(&path, "paths.output_dir", "x"),
            "Field is not editable: paths.output_dir"
        );
        assert_eq!(
            apply_field_error(&path, "llm.unknown", "x"),
            "Unknown LLM field: unknown"
        );
        assert_eq!(
            apply_field_error(&path, "paths.input_dir", ""),
            "[paths] input_dir cannot be empty"
        );
        assert_eq!(
            apply_field_error(&path, "image.grayscale", "perhaps"),
            "Invalid boolean value: perhaps"
        );
    }

    #[test]
    fn optional_ints_map_zero_and_empty_to_none() {
        let dir = tempfile::tempdir().unwrap();
        let path = write_base(dir.path());

        save_changes(
            &path,
            &map(&[("llm.eval_batch_size", ""), ("llm.context_length", "0")]),
        )
        .unwrap();

        let (cfg, _) = load_config(&path, false).unwrap();
        assert_eq!(cfg.llm.eval_batch_size, None);
        assert_eq!(cfg.llm.context_length, None);
    }

    #[test]
    fn backup_names_are_timestamped_bak_files() {
        let dir = tempfile::tempdir().unwrap();
        let path = write_base(dir.path());
        let outcome = save_changes(&path, &map(&[("llm.workers", "3")])).unwrap();
        let backup = outcome.backup_path.unwrap();
        let name = backup.file_name().unwrap().to_string_lossy().to_string();
        assert!(
            name.starts_with("forza_config.ini.2") && name.ends_with(".bak"),
            "unexpected backup name: {name}"
        );
        assert!(backup.exists());
    }

    fn apply_field_error(path: &Path, field: &str, value: &str) -> String {
        let mut changes = std::collections::BTreeMap::new();
        changes.insert(field.to_string(), value.to_string());
        candidate_config(path, &changes).unwrap_err()
    }
}
