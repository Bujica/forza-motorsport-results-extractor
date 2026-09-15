//! Settings page model — port of the Python `SettingsController` snapshot:
//! editable rows grouped into Paths / Backend-Model-Prompt /
//! Runtime-Image-PDF-Validation, path status badges, pending-change
//! overrides, and the same validation message contract.

use std::collections::BTreeMap;
use std::path::Path;

use forza_config::AppConfig;
use forza_config::keys;

#[derive(Debug, Clone, PartialEq)]
pub struct SettingRow {
    /// Full editable key (`llm.url`, `user.gamertag`, …).
    pub key: String,
    /// Short display name (`url`, `gamertag`, …).
    pub name: String,
    pub value: String,
    /// `ok`, `invalid`, `missing`, or `pending` while edited.
    pub status: String,
    /// `text`, `int`, `float`, `bool`, or `choice`.
    pub editor: String,
    /// Choice options; for int/float editors `min;max;step`.
    pub options: Vec<String>,
    pub group: &'static str,
}

#[derive(Debug, Clone, PartialEq)]
pub struct SettingsSnapshot {
    pub rows: Vec<SettingRow>,
    pub validation_ok: bool,
    pub validation_message: String,
    pub dirty: bool,
}

pub const GROUP_PATHS: &str = "Paths";
pub const GROUP_LLM: &str = "Backend / Model / Prompt";
pub const GROUP_RUNTIME: &str = "Runtime / Image / PDF / Validation";
pub const GROUP_UI: &str = "UI";

const OK_MESSAGE: &str = "Configuration is valid for execution.";

/// Build the snapshot for the current config, applying `pending` edits on
/// top (status becomes `pending`). `validation_override` carries a preview
/// or failed-save verdict; otherwise the config is validated as-is.
pub fn settings_snapshot(
    cfg: &AppConfig,
    pending: &BTreeMap<String, String>,
    dirty: bool,
    validation_override: Option<(bool, String)>,
) -> SettingsSnapshot {
    let (validation_ok, validation_message) =
        validation_override.unwrap_or_else(|| validate_message(cfg));
    let mut rows = Vec::new();
    rows.extend(path_rows(cfg));
    rows.extend(llm_rows(cfg));
    rows.extend(runtime_rows(cfg));
    rows.extend(ui_rows(cfg));
    for row in &mut rows {
        if let Some(value) = pending.get(&row.key) {
            row.value = value.clone();
            row.status = "pending".to_string();
        }
    }
    SettingsSnapshot {
        rows,
        validation_ok,
        validation_message,
        dirty,
    }
}

fn validate_message(cfg: &AppConfig) -> (bool, String) {
    match forza_config::validate_config(cfg) {
        Ok(()) => (true, OK_MESSAGE.to_string()),
        Err(errors) => (false, forza_config::save::format_validation_errors(&errors)),
    }
}

fn row(key: &str, name: &str, value: String, editor: &str, group: &'static str) -> SettingRow {
    SettingRow {
        key: key.to_string(),
        name: name.to_string(),
        value,
        status: "ok".to_string(),
        editor: editor.to_string(),
        options: Vec::new(),
        group,
    }
}

fn int_options(min: i64, max: i64, step: i64) -> Vec<String> {
    vec![min.to_string(), max.to_string(), step.to_string()]
}

fn float_options(min: &str, max: &str, step: &str) -> Vec<String> {
    vec![min.to_string(), max.to_string(), step.to_string()]
}

fn path_rows(cfg: &AppConfig) -> Vec<SettingRow> {
    vec![
        SettingRow {
            status: dir_status(&cfg.input_dir),
            ..row(
                keys::PATHS_INPUT_DIR,
                "input_dir",
                cfg.input_dir.to_string_lossy().to_string(),
                "text",
                GROUP_PATHS,
            )
        },
        SettingRow {
            status: parent_status(&cfg.pdf_file),
            ..row(
                keys::PATHS_PDF_FILE,
                "pdf_file",
                cfg.pdf_file.to_string_lossy().to_string(),
                "text",
                GROUP_PATHS,
            )
        },
        SettingRow {
            status: parent_status(&cfg.log_file),
            ..row(
                keys::PATHS_LOG_FILE,
                "log_file",
                cfg.log_file.to_string_lossy().to_string(),
                "text",
                GROUP_PATHS,
            )
        },
    ]
}

fn llm_rows(cfg: &AppConfig) -> Vec<SettingRow> {
    let llm = &cfg.llm;
    let mut prompt_ids: Vec<String> = forza_config::prompts::PROMPT_IDS
        .iter()
        .map(|s| s.to_string())
        .collect();
    prompt_ids.sort();
    vec![
        row(keys::LLM_URL, "url", llm.url.clone(), "text", GROUP_LLM),
        row(
            keys::LLM_MODEL,
            "model",
            llm.model.clone(),
            "text",
            GROUP_LLM,
        ),
        SettingRow {
            options: prompt_ids,
            ..row(
                keys::PROMPT_ACTIVE,
                keys::PROMPT_ACTIVE,
                cfg.prompt.active.clone(),
                "choice",
                GROUP_LLM,
            )
        },
        SettingRow {
            options: int_options(64, 8192, 64),
            ..row(
                keys::LLM_MAX_COMPLETION_TOKENS,
                "max_completion_tokens",
                llm.max_completion_tokens.to_string(),
                "int",
                GROUP_LLM,
            )
        },
        SettingRow {
            options: float_options("0", "2", "0.05"),
            ..row(
                keys::LLM_TEMPERATURE,
                "temperature",
                py_float(llm.temperature),
                "float",
                GROUP_LLM,
            )
        },
        SettingRow {
            options: int_options(1, 120, 1),
            ..row(
                keys::LLM_TIMEOUT_CONNECT,
                "timeout_connect",
                llm.timeout_connect.to_string(),
                "int",
                GROUP_LLM,
            )
        },
        SettingRow {
            options: int_options(10, 900, 10),
            ..row(
                keys::LLM_TIMEOUT_READ,
                "timeout_read",
                llm.timeout_read.to_string(),
                "int",
                GROUP_LLM,
            )
        },
        SettingRow {
            options: int_options(0, 10, 1),
            ..row(
                keys::LLM_MAX_RETRIES,
                "max_retries",
                llm.max_retries.to_string(),
                "int",
                GROUP_LLM,
            )
        },
        SettingRow {
            options: vec!["png".into(), "jpeg".into(), "webp".into()],
            ..row(
                keys::LLM_IMAGE_FORMAT,
                "image_format",
                llm.image_format.clone(),
                "choice",
                GROUP_LLM,
            )
        },
        SettingRow {
            options: int_options(0, 32768, 256),
            ..row(
                keys::LLM_CONTEXT_LENGTH,
                "context_length",
                opt_str(llm.context_length),
                "int",
                GROUP_LLM,
            )
        },
        SettingRow {
            options: ["off", "on", "auto", "low", "medium", "high"]
                .iter()
                .map(|s| s.to_string())
                .collect(),
            ..row(
                keys::LLM_REASONING_MODE,
                "reasoning_mode",
                llm.reasoning_mode.clone().unwrap_or_default(),
                "choice",
                GROUP_LLM,
            )
        },
        SettingRow {
            options: int_options(0, 4096, 64),
            ..row(
                keys::LLM_EVAL_BATCH_SIZE,
                "eval_batch_size",
                opt_str(llm.eval_batch_size),
                "int",
                GROUP_LLM,
            )
        },
        SettingRow {
            options: int_options(0, 4096, 64),
            ..row(
                keys::LLM_PHYSICAL_BATCH_SIZE,
                "physical_batch_size",
                opt_str(llm.physical_batch_size),
                "int",
                GROUP_LLM,
            )
        },
        row(
            keys::LLM_FLASH_ATTENTION,
            "flash_attention",
            py_bool(llm.flash_attention).to_string(),
            "bool",
            GROUP_LLM,
        ),
        row(
            keys::LLM_OFFLOAD_KV_CACHE_TO_GPU,
            "offload_kv_cache_to_gpu",
            py_bool(llm.offload_kv_cache_to_gpu).to_string(),
            "bool",
            GROUP_LLM,
        ),
    ]
}

fn ui_rows(cfg: &AppConfig) -> Vec<SettingRow> {
    vec![
        SettingRow {
            options: float_options("0.5", "2.5", "0.05"),
            ..row(
                keys::UI_FONT_SCALE,
                "font_scale",
                py_float(cfg.ui.font_scale),
                "float",
                GROUP_UI,
            )
        },
        SettingRow {
            options: int_options(8, 24, 1),
            ..row(
                keys::UI_MIN_FONT_PX,
                "min_font_px",
                cfg.ui.min_font_px.to_string(),
                "int",
                GROUP_UI,
            )
        },
    ]
}

fn runtime_rows(cfg: &AppConfig) -> Vec<SettingRow> {
    vec![
        row(
            keys::USER_GAMERTAG,
            "gamertag",
            cfg.gamertag.clone(),
            "text",
            GROUP_RUNTIME,
        ),
        SettingRow {
            options: int_options(1, 16, 1),
            ..row(
                keys::LLM_WORKERS,
                "workers",
                cfg.workers.to_string(),
                "int",
                GROUP_RUNTIME,
            )
        },
        SettingRow {
            options: int_options(1, 16, 1),
            ..row(
                keys::LLM_INFERENCE_CONCURRENCY,
                "inference_concurrency",
                cfg.inference_concurrency.to_string(),
                "int",
                GROUP_RUNTIME,
            )
        },
        SettingRow {
            options: int_options(640, 4096, 64),
            ..row(
                keys::IMAGE_MAX_WIDTH,
                keys::IMAGE_MAX_WIDTH,
                cfg.image.max_width.to_string(),
                "int",
                GROUP_RUNTIME,
            )
        },
        SettingRow {
            options: int_options(1, 100, 1),
            ..row(
                keys::IMAGE_ENCODE_QUALITY,
                keys::IMAGE_ENCODE_QUALITY,
                cfg.image.encode_quality.to_string(),
                "int",
                GROUP_RUNTIME,
            )
        },
        row(
            keys::IMAGE_GRAYSCALE,
            keys::IMAGE_GRAYSCALE,
            py_bool(cfg.image.grayscale).to_string(),
            "bool",
            GROUP_RUNTIME,
        ),
        SettingRow {
            options: float_options("-100", "250", "1"),
            ..row(
                keys::VALIDATION_TEMP_MIN_F,
                keys::VALIDATION_TEMP_MIN_F,
                py_float(cfg.validation.temp_min_f),
                "float",
                GROUP_RUNTIME,
            )
        },
        SettingRow {
            options: float_options("-100", "250", "1"),
            ..row(
                keys::VALIDATION_TEMP_MAX_F,
                keys::VALIDATION_TEMP_MAX_F,
                py_float(cfg.validation.temp_max_f),
                "float",
                GROUP_RUNTIME,
            )
        },
        row(
            keys::PDF_DIRTY_LAP_SYMBOL,
            keys::PDF_DIRTY_LAP_SYMBOL,
            cfg.pdf.dirty_lap_symbol.clone(),
            "text",
            GROUP_RUNTIME,
        ),
        row(
            keys::PDF_SHOW_DIRTY_LAP_SYMBOL,
            keys::PDF_SHOW_DIRTY_LAP_SYMBOL,
            py_bool(cfg.pdf.show_dirty_lap_symbol).to_string(),
            "bool",
            GROUP_RUNTIME,
        ),
    ]
}

fn dir_status(path: &Path) -> String {
    if path.is_dir() {
        "ok".to_string()
    } else if path.exists() {
        "invalid".to_string()
    } else {
        "missing".to_string()
    }
}

fn parent_status(path: &Path) -> String {
    match path.parent() {
        Some(parent) if parent.as_os_str().is_empty() => "missing".to_string(),
        Some(parent) => dir_status(parent),
        None => "missing".to_string(),
    }
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

/// Python `str(float)` — keeps the trailing `.0`.
fn py_float(value: f64) -> String {
    format!("{value:?}")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn default_cfg() -> AppConfig {
        // A missing path loads pure defaults (documented load_config behavior).
        let path = Path::new("Z:/nonexistent/forza_config.ini");
        let (cfg, warnings) = forza_config::load_config(path, false).unwrap();
        // Only the announced "not found → defaults" warning is expected.
        assert!(
            warnings.iter().all(|w| w.contains("not found")),
            "{warnings:?}"
        );
        cfg
    }

    #[test]
    fn snapshot_groups_and_editable_keys_match_python_controller() {
        let cfg = default_cfg();
        let snapshot = settings_snapshot(&cfg, &BTreeMap::new(), false, None);

        let keys: Vec<&str> = snapshot.rows.iter().map(|r| r.key.as_str()).collect();
        // Single spelling: the snapshot emits exactly the known key set, in
        // display order. A new setting without display wiring (or a typo on
        // either side) fails here.
        assert_eq!(keys, keys::ALL_EDITABLE);
        assert!(snapshot.validation_ok);
        assert_eq!(snapshot.validation_message, OK_MESSAGE);
    }

    #[test]
    fn pending_overrides_mark_rows_pending() {
        let cfg = default_cfg();
        let mut pending = BTreeMap::new();
        pending.insert(keys::USER_GAMERTAG.to_string(), "NewTag".to_string());
        let snapshot = settings_snapshot(&cfg, &pending, true, None);
        let gamertag = snapshot
            .rows
            .iter()
            .find(|r| r.key == keys::USER_GAMERTAG)
            .unwrap();
        assert_eq!(gamertag.value, "NewTag");
        assert_eq!(gamertag.status, "pending");
        assert!(snapshot.dirty);
        // Unedited rows keep their persisted value.
        let workers = snapshot
            .rows
            .iter()
            .find(|r| r.key == keys::LLM_WORKERS)
            .unwrap();
        assert_eq!(workers.value, "1");
        assert_eq!(workers.status, "ok");
    }

    #[test]
    fn validation_override_surfaces_failure() {
        let cfg = default_cfg();
        let snapshot = settings_snapshot(
            &cfg,
            &BTreeMap::new(),
            false,
            Some((false, "Configuration errors:\n  \u{2022} boom".to_string())),
        );
        assert!(!snapshot.validation_ok);
        assert!(snapshot.validation_message.contains("boom"));
    }

    #[test]
    fn path_status_reflects_filesystem() {
        let mut cfg = default_cfg();
        cfg.input_dir = std::path::PathBuf::from("Z:/definitely/not/here");
        cfg.pdf_file = std::path::PathBuf::from("Z:/definitely/not/here/report.pdf");
        let snapshot = settings_snapshot(&cfg, &BTreeMap::new(), false, None);
        let input = snapshot
            .rows
            .iter()
            .find(|r| r.key == keys::PATHS_INPUT_DIR)
            .unwrap();
        let pdf = snapshot
            .rows
            .iter()
            .find(|r| r.key == keys::PATHS_PDF_FILE)
            .unwrap();
        assert_eq!(input.status, "missing");
        assert_eq!(pdf.status, "missing");
    }

    #[test]
    fn config_dirty_default_is_parseable() {
        // The render default must stay inside the parse set: otherwise the
        // PDF writes a mark the parser (and the doctor) cannot see.
        // `forza-domain` cannot depend on `forza-config` (leaf direction),
        // so the cross-check lives here where both are visible.
        let cfg = default_cfg();
        for symbol in cfg.pdf.dirty_lap_symbol.chars() {
            assert!(
                forza_domain::lap::DEFAULT_DIRTY_SYMBOLS.contains(symbol),
                "render default {symbol:?} not in parse set"
            );
        }
    }
}
