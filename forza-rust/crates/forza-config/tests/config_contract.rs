// Test harness code: unwraps are the idiomatic assertion helpers here.
#![allow(clippy::unwrap_used)]

use forza_config::{AppConfig, load_config, validate_config};
use std::path::Path;

const FULL_INI: &str = "\
[paths]
input_dir = shots
pdf_file = out/report.pdf
log_file = logs/app.log
database_file = db/forza.sqlite3

[user]
gamertag = TestDriver

[llm]
workers = 4

[lmstudio]
url = http://127.0.0.1:9999/api/v1/chat
model = test-model
max_completion_tokens = 800
temperature = 0.25
timeout_connect = 5
timeout_read = 60
max_retries = 2
image_format = jpeg
context_length = 8192
reasoning_mode = high
eval_batch_size = 512
physical_batch_size = 256
flash_attention = false
offload_kv_cache_to_gpu = no
performance_tps_floor = 15.5
performance_reload_elapsed_s = 30.0
performance_reload_streak = 5

[image]
max_width = 1920
encode_quality = 90
grayscale = false

[validation]
temp_min_f = 50
temp_max_f = 130

[pdf]
dirty_lap_symbol = x
show_dirty_lap_symbol = false

[prompt]
active = user_header_shaped_v1
";

fn write_ini(dir: &Path, name: &str, content: &str) -> std::path::PathBuf {
    let path = dir.join(name);
    std::fs::write(&path, content).unwrap();
    path
}

#[test]
fn missing_file_yields_python_defaults() {
    let (cfg, warnings) = load_config(Path::new("definitely_missing.ini"), false).unwrap();
    assert!(warnings.is_empty());
    assert_eq!(cfg.gamertag, "Player");
    assert_eq!(cfg.workers, 1);
    assert_eq!(cfg.llm.url, "http://127.0.0.1:1234/api/v1/chat");
    assert_eq!(cfg.llm.model, "qwen/qwen3.5-9b");
    assert_eq!(cfg.llm.max_completion_tokens, 1000);
    assert_eq!(cfg.llm.temperature, 0.0);
    assert_eq!(cfg.llm.timeout_connect, 10);
    assert_eq!(cfg.llm.timeout_read, 180);
    assert_eq!(cfg.llm.max_retries, 3);
    assert_eq!(cfg.llm.image_format, "png");
    assert_eq!(cfg.llm.context_length, Some(5000));
    assert_eq!(cfg.llm.reasoning_mode.as_deref(), Some("off"));
    assert_eq!(cfg.llm.eval_batch_size, Some(1024));
    assert_eq!(cfg.llm.physical_batch_size, None);
    assert!(cfg.llm.flash_attention);
    assert!(cfg.llm.offload_kv_cache_to_gpu);
    assert_eq!(cfg.llm.performance_tps_floor, 20.0);
    assert_eq!(cfg.llm.performance_reload_elapsed_s, 45.0);
    assert_eq!(cfg.llm.performance_reload_streak, 3);
    assert_eq!(cfg.image.max_width, 2560);
    assert_eq!(cfg.image.encode_quality, 85);
    assert!(cfg.image.grayscale);
    assert_eq!(cfg.validation.temp_min_f, 40.0);
    assert_eq!(cfg.validation.temp_max_f, 140.0);
    assert_eq!(cfg.pdf.dirty_lap_symbol, "\u{2020}");
    assert!(cfg.pdf.show_dirty_lap_symbol);
    assert_eq!(cfg.prompt.active, "user_header_shaped_v1");
    assert!(validate_config(&cfg).is_ok());
}

#[test]
fn full_ini_overrides_every_section() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_ini(dir.path(), "full.ini", FULL_INI);
    let (cfg, warnings) = load_config(&path, false).unwrap();
    assert!(warnings.is_empty());
    assert_eq!(cfg.input_dir, Path::new("shots"));
    assert_eq!(cfg.database_file, Path::new("db/forza.sqlite3"));
    assert_eq!(cfg.gamertag, "TestDriver");
    assert_eq!(cfg.workers, 4);
    assert_eq!(cfg.llm.temperature, 0.25);
    assert_eq!(cfg.llm.context_length, Some(8192));
    assert_eq!(cfg.llm.reasoning_mode.as_deref(), Some("high"));
    assert_eq!(cfg.llm.physical_batch_size, Some(256));
    assert!(!cfg.llm.flash_attention);
    assert!(!cfg.llm.offload_kv_cache_to_gpu);
    assert_eq!(cfg.llm.performance_tps_floor, 15.5);
    assert_eq!(cfg.llm.performance_reload_streak, 5);
    assert_eq!(cfg.pdf.dirty_lap_symbol, "x");
    assert!(!cfg.pdf.show_dirty_lap_symbol);
    assert!(validate_config(&cfg).is_ok());
}

#[test]
fn invalid_values_warn_and_fall_back_leniently() {
    let ini = "\
[lmstudio]
temperature = not-a-number
context_length = zero
image_format = bmp
[image]
max_width = 9999999
";
    let dir = tempfile::tempdir().unwrap();
    let path = write_ini(dir.path(), "bad.ini", ini);
    let (cfg, warnings) = load_config(&path, false).unwrap();
    assert_eq!(cfg.llm.temperature, 0.0, "falls back to default");
    assert_eq!(cfg.llm.context_length, Some(5000));
    assert_eq!(cfg.llm.image_format, "bmp", "strings are taken as-is");
    assert_eq!(cfg.image.max_width, 9999999);
    assert_eq!(warnings.len(), 2, "{warnings:?}");
    let errors = validate_config(&cfg).unwrap_err();
    assert_eq!(errors.len(), 2, "{errors:?}");
    assert!(errors.iter().any(|e| e.contains("image_format")));
    assert!(errors.iter().any(|e| e.contains("max_width")));
}

#[test]
fn strict_mode_fails_on_first_invalid_value() {
    let ini = "\
[lmstudio]
temperature = oops
timeout_read = -5
";
    let dir = tempfile::tempdir().unwrap();
    let path = write_ini(dir.path(), "strict.ini", ini);
    let err = load_config(&path, true).unwrap_err();
    assert!(
        err.message.contains("[lmstudio] temperature"),
        "{}",
        err.message
    );
}

#[test]
fn empty_optional_values_become_none() {
    let ini = "\
[lmstudio]
context_length =
reasoning_mode =
";
    let dir = tempfile::tempdir().unwrap();
    let path = write_ini(dir.path(), "empty.ini", ini);
    let (cfg, _) = load_config(&path, false).unwrap();
    assert_eq!(cfg.llm.context_length, None);
    assert_eq!(cfg.llm.reasoning_mode, None);
}

#[test]
fn validation_collects_all_failures() {
    let mut cfg = AppConfig {
        input_dir: "in".into(),
        pdf_file: "p".into(),
        log_file: "l".into(),
        database_file: "d".into(),
        gamertag: "g".into(),
        workers: 0,
        llm: forza_config::LlmConfig {
            url: String::new(),
            model: String::new(),
            max_completion_tokens: 1,
            temperature: 0.0,
            timeout_connect: 0,
            timeout_read: 0,
            max_retries: 1,
            image_format: "gif".into(),
            context_length: Some(0),
            reasoning_mode: Some("maybe".into()),
            eval_batch_size: None,
            physical_batch_size: None,
            flash_attention: true,
            offload_kv_cache_to_gpu: true,
            performance_tps_floor: 1.0,
            performance_reload_elapsed_s: 1.0,
            performance_reload_streak: 0,
        },
        image: forza_config::ImageConfig {
            max_width: 100,
            encode_quality: 0,
            grayscale: true,
        },
        validation: forza_config::ValidationConfig {
            temp_min_f: 100.0,
            temp_max_f: 90.0,
        },
        pdf: forza_config::PdfConfig {
            dirty_lap_symbol: "!".into(),
            show_dirty_lap_symbol: true,
        },
        prompt: forza_config::PromptConfig {
            active: "nope".into(),
        },
    };
    cfg.workers = 0;
    let errors = validate_config(&cfg).unwrap_err();
    for fragment in [
        "image_format",
        "reasoning_mode",
        "[prompt] active",
        "workers",
        "timeout_read",
        "timeout_connect",
        "context_length",
        "performance_reload_streak",
        "max_width",
        "encode_quality",
        "temp_min_f",
    ] {
        assert!(
            errors.iter().any(|e| e.contains(fragment)),
            "missing {fragment} in {errors:?}"
        );
    }
}
