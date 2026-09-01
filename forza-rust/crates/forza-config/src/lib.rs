// Unit-test modules exercise fallible helpers directly.
#![cfg_attr(test, allow(clippy::unwrap_used, clippy::expect_used))]

//! `.ini` configuration loading, defaults, and validation.
//!
//! Mirrors the Python `forza/config.py` contract: same sections, keys,
//! defaults, and validation messages. Invalid values either fail fast
//! (`strict`) or produce collected warnings with the documented fallback.

pub mod ini;
pub mod prompts;
pub mod save;

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use thiserror::Error;

/// Configuration errors that abort loading.
#[derive(Debug, Error)]
#[error("{message}")]
pub struct ConfigError {
    pub message: String,
}

impl ConfigError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

/// Collected non-fatal problems from lenient loading.
pub type Warnings = Vec<String>;

#[derive(Debug, Clone, PartialEq)]
pub struct LlmConfig {
    pub url: String,
    pub model: String,
    pub max_completion_tokens: i64,
    pub temperature: f64,
    pub timeout_connect: i64,
    pub timeout_read: i64,
    pub max_retries: i64,
    /// One of `jpeg`, `png`, `webp`.
    pub image_format: String,
    pub context_length: Option<i64>,
    /// One of `off`, `on`, `auto`, `low`, `medium`, `high`, or absent.
    pub reasoning_mode: Option<String>,
    pub eval_batch_size: Option<i64>,
    pub physical_batch_size: Option<i64>,
    pub flash_attention: bool,
    pub offload_kv_cache_to_gpu: bool,
    pub performance_tps_floor: f64,
    pub performance_reload_elapsed_s: f64,
    pub performance_reload_streak: i64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ImageConfig {
    pub max_width: i64,
    pub encode_quality: i64,
    pub grayscale: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ValidationConfig {
    pub temp_min_f: f64,
    pub temp_max_f: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PdfConfig {
    pub dirty_lap_symbol: String,
    pub show_dirty_lap_symbol: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PromptConfig {
    pub active: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct UiConfig {
    /// Global font scale factor (e.g. 1.0 = 100%, 1.25 = QuadHD comfort)
    pub font_scale: f64,
    /// Absolute minimum font size in px, clamps the scaled xs/sm/md values
    pub min_font_px: i64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct AppConfig {
    pub input_dir: PathBuf,
    pub pdf_file: PathBuf,
    pub log_file: PathBuf,
    pub database_file: PathBuf,
    pub gamertag: String,
    pub workers: i64,
    pub llm: LlmConfig,
    pub image: ImageConfig,
    pub validation: ValidationConfig,
    pub pdf: PdfConfig,
    pub prompt: PromptConfig,
    pub ui: UiConfig,
}

const LM_DEFAULT_URL: &str = "http://127.0.0.1:1234/api/v1/chat";
const LM_DEFAULT_MODEL: &str = "qwen/qwen3.5-9b";
const LM_DEFAULT_TIMEOUT_CONNECT: i64 = 10;
const LM_DEFAULT_TIMEOUT_READ: i64 = 180;
const LM_DEFAULT_IMAGE_FORMAT: &str = "png";
const LM_DEFAULT_CONTEXT_LENGTH: i64 = 5000;
const LM_DEFAULT_REASONING_MODE: &str = "off";
const LM_DEFAULT_EVAL_BATCH_SIZE: i64 = 1024;

const VALID_IMAGE_FORMATS: &[&str] = &["jpeg", "png", "webp"];
const VALID_REASONING_MODES: &[&str] = &["off", "on", "auto", "low", "medium", "high"];

type Sections = HashMap<String, HashMap<String, String>>;

fn read_ini(path: &Path) -> Sections {
    let mut ini = configparser::ini::Ini::new();
    match ini.load(path) {
        Ok(map) => map
            .into_iter()
            .map(|(section, kv)| {
                let cleaned = kv
                    .into_iter()
                    .filter_map(|(k, v)| v.map(|value| (k, value)))
                    .collect();
                (section, cleaned)
            })
            .collect(),
        Err(_) => HashMap::new(),
    }
}

struct Parsed<T> {
    value: T,
    invalid: Option<String>,
}

fn parse_int(raw: &str, section: &str, key: &str) -> Parsed<i64> {
    match raw.trim().parse::<i64>() {
        Ok(v) => Parsed {
            value: v,
            invalid: None,
        },
        Err(e) => Parsed {
            value: 0,
            invalid: Some(format!("Invalid config value [{section}] {key}: {e}")),
        },
    }
}

fn parse_float(raw: &str, section: &str, key: &str) -> Parsed<f64> {
    match raw.trim().parse::<f64>() {
        Ok(v) => Parsed {
            value: v,
            invalid: None,
        },
        Err(e) => Parsed {
            value: 0.0,
            invalid: Some(format!("Invalid config value [{section}] {key}: {e}")),
        },
    }
}

fn parse_bool(raw: &str, section: &str, key: &str) -> Parsed<bool> {
    match raw.trim().to_lowercase().as_str() {
        "1" | "yes" | "true" | "on" => Parsed {
            value: true,
            invalid: None,
        },
        "0" | "no" | "false" | "off" => Parsed {
            value: false,
            invalid: None,
        },
        other => Parsed {
            value: false,
            invalid: Some(format!(
                "Invalid config value [{section}] {key}: not a boolean: {other}"
            )),
        },
    }
}

/// Loader context tracking the first strict failure while collecting warnings.
struct Loader<'a> {
    map: &'a Sections,
    strict: bool,
    warnings: &'a mut Warnings,
    first_error: Option<ConfigError>,
}

impl<'a> Loader<'a> {
    fn raw(&self, section: &str, key: &str) -> Option<String> {
        self.map.get(section).and_then(|kv| kv.get(key)).cloned()
    }

    fn record_invalid<T>(&mut self, parsed: Parsed<T>, fallback: T) -> T {
        match parsed.invalid {
            None => parsed.value,
            Some(message) => {
                if self.strict && self.first_error.is_none() {
                    self.first_error = Some(ConfigError::new(message.clone()));
                }
                self.warnings.push(message);
                fallback
            }
        }
    }

    fn string(&self, section: &str, key: &str, fallback: &str) -> String {
        self.raw(section, key)
            .unwrap_or_else(|| fallback.to_string())
    }

    fn int(&mut self, section: &'static str, key: &'static str, fallback: i64) -> i64 {
        match self.raw(section, key) {
            None => fallback,
            Some(text) => {
                let parsed = parse_int(&text, section, key);
                self.record_invalid(parsed, fallback)
            }
        }
    }

    fn opt_int(
        &mut self,
        section: &'static str,
        key: &'static str,
        fallback: Option<i64>,
    ) -> Option<i64> {
        match self.raw(section, key) {
            None => fallback,
            Some(text) if text.trim().is_empty() => None,
            Some(text) => {
                let parsed = parse_int(&text, section, key);
                match parsed.invalid {
                    None => Some(parsed.value),
                    Some(message) => {
                        if self.strict && self.first_error.is_none() {
                            self.first_error = Some(ConfigError::new(message.clone()));
                        }
                        self.warnings.push(message);
                        fallback
                    }
                }
            }
        }
    }

    fn float(&mut self, section: &'static str, key: &'static str, fallback: f64) -> f64 {
        match self.raw(section, key) {
            None => fallback,
            Some(text) => {
                let parsed = parse_float(&text, section, key);
                self.record_invalid(parsed, fallback)
            }
        }
    }

    fn boolean(&mut self, section: &'static str, key: &'static str, fallback: bool) -> bool {
        match self.raw(section, key) {
            None => fallback,
            Some(text) => {
                let parsed = parse_bool(&text, section, key);
                self.record_invalid(parsed, fallback)
            }
        }
    }
}

/// Load configuration from an INI file. Missing files yield all defaults.
///
/// With `strict=true`, the first invalid value aborts with [`ConfigError`];
/// otherwise invalid values are appended to warnings and their defaults used,
/// mirroring the Python lenient behavior.
pub fn load_config(path: &Path, strict: bool) -> Result<(AppConfig, Warnings), ConfigError> {
    let mut warnings = Warnings::new();
    let map = read_ini(path);
    let mut loader = Loader {
        map: &map,
        strict,
        warnings: &mut warnings,
        first_error: None,
    };

    let url = loader.string("lmstudio", "url", LM_DEFAULT_URL);
    let model = loader.string("lmstudio", "model", LM_DEFAULT_MODEL);
    let max_completion_tokens = loader.int("lmstudio", "max_completion_tokens", 1000);
    let temperature = loader.float("lmstudio", "temperature", 0.0);
    let timeout_connect = loader.int("lmstudio", "timeout_connect", LM_DEFAULT_TIMEOUT_CONNECT);
    let timeout_read = loader.int("lmstudio", "timeout_read", LM_DEFAULT_TIMEOUT_READ);
    let max_retries = loader.int("lmstudio", "max_retries", 3);
    let image_format = loader.string("lmstudio", "image_format", LM_DEFAULT_IMAGE_FORMAT);
    let context_length = loader.opt_int(
        "lmstudio",
        "context_length",
        Some(LM_DEFAULT_CONTEXT_LENGTH),
    );
    let reasoning_mode = match loader.raw("lmstudio", "reasoning_mode") {
        None => Some(LM_DEFAULT_REASONING_MODE.to_string()),
        Some(v) if v.is_empty() => None,
        Some(v) => Some(v),
    };
    let eval_batch_size = loader.opt_int(
        "lmstudio",
        "eval_batch_size",
        Some(LM_DEFAULT_EVAL_BATCH_SIZE),
    );
    let physical_batch_size = loader.opt_int("lmstudio", "physical_batch_size", None);
    let flash_attention = loader.boolean("lmstudio", "flash_attention", true);
    let offload_kv_cache_to_gpu = loader.boolean("lmstudio", "offload_kv_cache_to_gpu", true);
    let performance_tps_floor = loader.float("lmstudio", "performance_tps_floor", 20.0);
    let performance_reload_elapsed_s =
        loader.float("lmstudio", "performance_reload_elapsed_s", 45.0);
    let performance_reload_streak = loader.int("lmstudio", "performance_reload_streak", 3);

    let workers = loader.int("llm", "workers", 1);

    let input_dir = loader.string("paths", "input_dir", "data/input");
    let pdf_file = loader.string("paths", "pdf_file", "output/reports/forza_bestlaps.pdf");
    let log_file = loader.string("paths", "log_file", "output/logs/forza_debug.log");
    let database_file = loader.string("paths", "database_file", "data/forza.sqlite3");
    let gamertag = loader.string("user", "gamertag", "Player");

    let max_width = loader.int("image", "max_width", 2560);
    let encode_quality = loader.int("image", "encode_quality", 85);
    let grayscale = loader.boolean("image", "grayscale", true);

    let temp_min_f = loader.float("validation", "temp_min_f", 40.0);
    let temp_max_f = loader.float("validation", "temp_max_f", 140.0);

    let dirty_lap_symbol = loader.string("pdf", "dirty_lap_symbol", "\u{2020}");
    let show_dirty_lap_symbol = loader.boolean("pdf", "show_dirty_lap_symbol", true);

    let active = loader.string("prompt", "active", prompts::DEFAULT_PROMPT_ID);

    let font_scale = loader.float("ui", "font_scale", 1.0);
    let min_font_px = loader.int("ui", "min_font_px", 13);

    if let Some(err) = loader.first_error.take() {
        return Err(err);
    }

    let app = AppConfig {
        input_dir: PathBuf::from(input_dir),
        pdf_file: PathBuf::from(pdf_file),
        log_file: PathBuf::from(log_file),
        database_file: PathBuf::from(database_file),
        gamertag,
        workers,
        llm: LlmConfig {
            url,
            model,
            max_completion_tokens,
            temperature,
            timeout_connect,
            timeout_read,
            max_retries,
            image_format,
            context_length,
            reasoning_mode,
            eval_batch_size,
            physical_batch_size,
            flash_attention,
            offload_kv_cache_to_gpu,
            performance_tps_floor,
            performance_reload_elapsed_s,
            performance_reload_streak,
        },
        image: ImageConfig {
            max_width,
            encode_quality,
            grayscale,
        },
        validation: ValidationConfig {
            temp_min_f,
            temp_max_f,
        },
        pdf: PdfConfig {
            dirty_lap_symbol,
            show_dirty_lap_symbol,
        },
        prompt: PromptConfig { active },
        ui: UiConfig {
            font_scale,
            min_font_px,
        },
    };

    Ok((app, warnings))
}

/// Validate a loaded configuration, returning every failure found.
pub fn validate_config(cfg: &AppConfig) -> Result<(), Vec<String>> {
    let mut errors: Vec<String> = Vec::new();

    if !VALID_IMAGE_FORMATS.contains(&cfg.llm.image_format.as_str()) {
        errors.push(format!(
            "[lmstudio] image_format={:?} is not valid. Must be one of: {:?}",
            cfg.llm.image_format,
            sorted(VALID_IMAGE_FORMATS)
        ));
    }
    if let Some(mode) = &cfg.llm.reasoning_mode
        && !VALID_REASONING_MODES.contains(&mode.as_str())
    {
        errors.push(format!(
            "[lmstudio] reasoning_mode={:?} is not valid. Must be one of: {:?}",
            mode,
            sorted(VALID_REASONING_MODES)
        ));
    }
    if !prompts::PROMPT_IDS.contains(&cfg.prompt.active.as_str()) {
        errors.push(format!(
            "[prompt] active={:?} is not a registered prompt. Available: {:?}",
            cfg.prompt.active,
            sorted(prompts::PROMPT_IDS)
        ));
    }
    if cfg.workers < 1 {
        errors.push(format!("[llm] workers={} must be >= 1", cfg.workers));
    }
    if cfg.llm.timeout_read <= 0 {
        errors.push(format!(
            "[lmstudio] timeout_read={} must be > 0",
            cfg.llm.timeout_read
        ));
    }
    if cfg.llm.timeout_connect <= 0 {
        errors.push(format!(
            "[lmstudio] timeout_connect={} must be > 0",
            cfg.llm.timeout_connect
        ));
    }
    if let Some(v) = cfg.llm.context_length
        && v <= 0
    {
        errors.push(format!("[lmstudio] context_length={v} must be > 0"));
    }
    if let Some(v) = cfg.llm.eval_batch_size
        && v <= 0
    {
        errors.push(format!("[lmstudio] eval_batch_size={v} must be > 0"));
    }
    if let Some(v) = cfg.llm.physical_batch_size
        && v <= 0
    {
        errors.push(format!("[lmstudio] physical_batch_size={v} must be > 0"));
    }
    if cfg.llm.performance_reload_streak < 1 {
        errors.push(format!(
            "[lmstudio] performance_reload_streak={} must be >= 1",
            cfg.llm.performance_reload_streak
        ));
    }
    if !(640..=4096).contains(&cfg.image.max_width) {
        errors.push(format!(
            "[image] max_width={} is out of range [640, 4096]",
            cfg.image.max_width
        ));
    }
    if !(1..=100).contains(&cfg.image.encode_quality) {
        errors.push(format!(
            "[image] encode_quality={} is out of range [1, 100]",
            cfg.image.encode_quality
        ));
    }
    if cfg.validation.temp_min_f >= cfg.validation.temp_max_f {
        errors.push(format!(
            "[validation] temp_min_f ({}) must be less than temp_max_f ({})",
            cfg.validation.temp_min_f, cfg.validation.temp_max_f
        ));
    }
    if !(0.5..=2.5).contains(&cfg.ui.font_scale) {
        errors.push(format!(
            "[ui] font_scale={} is out of range [0.5, 2.5]",
            cfg.ui.font_scale
        ));
    }
    if !(8..=24).contains(&cfg.ui.min_font_px) {
        errors.push(format!(
            "[ui] min_font_px={} is out of range [8, 24]",
            cfg.ui.min_font_px
        ));
    }

    if errors.is_empty() {
        Ok(())
    } else {
        Err(errors)
    }
}

fn sorted<'a>(values: &'a [&'a str]) -> Vec<&'a str> {
    let mut v: Vec<&str> = values.to_vec();
    v.sort_unstable();
    v
}
