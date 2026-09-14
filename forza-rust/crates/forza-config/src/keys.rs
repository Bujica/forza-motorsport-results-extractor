//! Dotted configuration keys as constants.
//!
//! Single spelling for the `section.field` vocabulary shared by the loader
//! (`lib.rs`), the save path (`save.rs`), the Settings snapshot
//! (`forza-app/src/services/settings.rs`), and tests. A typo in any of
//! those places used to become silent unknown/ignored instead of an error;
//! misspelling a const name fails to compile, misspelling a const value
//! fails the key-set test in `settings.rs`.
//!
//! Bare per-section field names in `save.rs` match arms stay literal: they
//! sit next to a catch-all `Err`, so a typo there is already loud.

// Section prefixes (with trailing dot) for `apply_field` dispatch.
pub const PREFIX_PATHS: &str = "paths.";
pub const PREFIX_LLM: &str = "llm.";
pub const PREFIX_IMAGE: &str = "image.";
pub const PREFIX_VALIDATION: &str = "validation.";
pub const PREFIX_PDF: &str = "pdf.";
pub const PREFIX_UI: &str = "ui.";

pub const PATHS_INPUT_DIR: &str = "paths.input_dir";
pub const PATHS_PDF_FILE: &str = "paths.pdf_file";
pub const PATHS_LOG_FILE: &str = "paths.log_file";
pub const PATHS_DATABASE_FILE: &str = "paths.database_file";

pub const USER_GAMERTAG: &str = "user.gamertag";

pub const LLM_URL: &str = "llm.url";
pub const LLM_MODEL: &str = "llm.model";
pub const LLM_MAX_COMPLETION_TOKENS: &str = "llm.max_completion_tokens";
pub const LLM_TEMPERATURE: &str = "llm.temperature";
pub const LLM_TIMEOUT_CONNECT: &str = "llm.timeout_connect";
pub const LLM_TIMEOUT_READ: &str = "llm.timeout_read";
pub const LLM_MAX_RETRIES: &str = "llm.max_retries";
pub const LLM_IMAGE_FORMAT: &str = "llm.image_format";
pub const LLM_CONTEXT_LENGTH: &str = "llm.context_length";
pub const LLM_REASONING_MODE: &str = "llm.reasoning_mode";
pub const LLM_EVAL_BATCH_SIZE: &str = "llm.eval_batch_size";
pub const LLM_PHYSICAL_BATCH_SIZE: &str = "llm.physical_batch_size";
pub const LLM_FLASH_ATTENTION: &str = "llm.flash_attention";
pub const LLM_OFFLOAD_KV_CACHE_TO_GPU: &str = "llm.offload_kv_cache_to_gpu";
pub const LLM_PERFORMANCE_TPS_FLOOR: &str = "llm.performance_tps_floor";
pub const LLM_PERFORMANCE_RELOAD_ELAPSED_S: &str = "llm.performance_reload_elapsed_s";
pub const LLM_PERFORMANCE_RELOAD_STREAK: &str = "llm.performance_reload_streak";
pub const LLM_WORKERS: &str = "llm.workers";
pub const LLM_INFERENCE_CONCURRENCY: &str = "llm.inference_concurrency";

pub const PROMPT_ACTIVE: &str = "prompt.active";

pub const IMAGE_MAX_WIDTH: &str = "image.max_width";
pub const IMAGE_ENCODE_QUALITY: &str = "image.encode_quality";
pub const IMAGE_GRAYSCALE: &str = "image.grayscale";

pub const VALIDATION_TEMP_MIN_F: &str = "validation.temp_min_f";
pub const VALIDATION_TEMP_MAX_F: &str = "validation.temp_max_f";

pub const PDF_DIRTY_LAP_SYMBOL: &str = "pdf.dirty_lap_symbol";
pub const PDF_SHOW_DIRTY_LAP_SYMBOL: &str = "pdf.show_dirty_lap_symbol";

pub const UI_FONT_SCALE: &str = "ui.font_scale";
pub const UI_MIN_FONT_PX: &str = "ui.min_font_px";

/// Every key rendered by the Settings snapshot, in display order
/// (`settings_snapshot` must emit exactly this sequence).
pub const ALL_EDITABLE: &[&str] = &[
    PATHS_INPUT_DIR,
    PATHS_PDF_FILE,
    PATHS_LOG_FILE,
    LLM_URL,
    LLM_MODEL,
    PROMPT_ACTIVE,
    LLM_MAX_COMPLETION_TOKENS,
    LLM_TEMPERATURE,
    LLM_TIMEOUT_CONNECT,
    LLM_TIMEOUT_READ,
    LLM_MAX_RETRIES,
    LLM_IMAGE_FORMAT,
    LLM_CONTEXT_LENGTH,
    LLM_REASONING_MODE,
    LLM_EVAL_BATCH_SIZE,
    LLM_PHYSICAL_BATCH_SIZE,
    LLM_FLASH_ATTENTION,
    LLM_OFFLOAD_KV_CACHE_TO_GPU,
    LLM_PERFORMANCE_TPS_FLOOR,
    LLM_PERFORMANCE_RELOAD_ELAPSED_S,
    LLM_PERFORMANCE_RELOAD_STREAK,
    USER_GAMERTAG,
    LLM_WORKERS,
    LLM_INFERENCE_CONCURRENCY,
    IMAGE_MAX_WIDTH,
    IMAGE_ENCODE_QUALITY,
    IMAGE_GRAYSCALE,
    VALIDATION_TEMP_MIN_F,
    VALIDATION_TEMP_MAX_F,
    PDF_DIRTY_LAP_SYMBOL,
    PDF_SHOW_DIRTY_LAP_SYMBOL,
    UI_FONT_SCALE,
    UI_MIN_FONT_PX,
];
