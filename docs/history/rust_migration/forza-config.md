Status: historical
Audience: developer, maintainer, LLM
Lifecycle: temporary (superseded by `migration_report.md` in this directory)
Scope: detailed porting analysis of `forza-rust/crates/forza-config` crate
Last verified: 2026-08-27
Supersedes: none
Related tests: `forza-rust/crates/forza-config/tests/config_contract.rs`

# Detailed porting analysis — forza-config

## Overview

INI configuration, defaults, validation and persistence. Ported from Python's `forza/config.py` + `forza/application/config_service.py`.

| File | Lines | Python Source | Status |
|------|-------|--------------|--------|
| `src/lib.rs` | 475 | `forza/config.py`, `forza/prompts.py` | **Ported** |
| `src/save.rs` | 574 | `forza/application/config_service.py` | **Ported** |
| `src/prompts.rs` | 18 | `forza/prompts.py` | **Partially ported** |
| `src/ini.rs` | 169 | Python `configparser` stdlib | **Ported** |
| `tests/config_contract.rs` | 239 | `forza/config.py`, contracts/configuration.md | **Ported** |

## src/lib.rs — Core configuration module

Python reference: `forza/config.py` (291 lines) — defines all config dataclasses, `load_config()`, `validate_config()`. Secondary: `forza/prompts.py` for default prompt ID.

Status: **Ported**. All structs, defaults, parsing and value-level validations faithfully reproduced.

**Structs ported:**
| Rust struct | Python class | Status |
|---|---|---|
| `LlmConfig` | `LLMConfig` | 17 fields match exactly |
| `ImageConfig` | `ImageConfig` | 3 fields match |
| `ValidationConfig` | `ValidationConfig` | 2 fields match |
| `PdfConfig` | `PDFConfig` | 2 fields match |
| `PromptConfig` | `PromptConfig` | 1 field matches |
| `AppConfig` | `AppConfig` | 10 fields (nested structs mirror nested dataclasses) |

**Constants/defaults:** All LM Studio defaults (`LM_DEFAULT_URL`, `LM_DEFAULT_MODEL`, etc.) identical to Python's `LMSTUDIO_DEFAULTS` dict. Non-LMStudio defaults (`workers=1`, paths, gamertag, image, validation, pdf) all match.

**Functions:** `load_config(path: &Path, strict: bool)` — ports entire Python function; uses custom INI reader instead of `configparser`. `validate_config(cfg: &AppConfig)` — returns `Result<(), Vec<String>>` (Python raises `ConfigValidationError`). Parsing helpers (`parse_int`, `parse_float`, `parse_bool`) mirror `_get()` cast logic with strict/lenient modes.

**Gap:** Rust does **not include** writable path checks (`_writable_path_checks`) that Python's `validate_config` performs (checks parent directory writability). All config-value validations present; filesystem-writability omitted.

## src/save.rs — Complete ConfigFileService

Python reference: `forza/application/config_service.py` (262 lines) — defines `ConfigFileService`, `ConfigSaveResult`.

Status: **Ported**. Entire save/backup/write/prune pipeline faithfully reproduced.

**Functions ported:**
- `candidate_config(path, changes)` — ports Python's `_candidate_config()`
- `validate_changes(path, changes)` — returns success/error message strings (Python returns `ConfigSaveResult` object)
- `save_changes(path, changes)` — loads base config, builds candidate, backs up, writes atomically, re-reads
- `apply_field()`, `apply_path()`, `apply_llm()`, `apply_image()`, `apply_validation()`, `apply_pdf()` — all mirror Python's `_apply*` methods exactly; field prefix stripping (`paths.`, `llm.` etc.) identical

**Obsolete key pruning:** All obsolete keys in `[paths]` pruned identically: `tracks_file`, `cars_file`, `output_dir`, `benchmark_file`, `raw_artifacts_dir`, `raw_dir`, `calibration_samples_dir`, `external_records_file`, `review_dir`, `corrections_dir`, `manual_overrides_file`. `[lmstudio]`: `api_family`, `max_parse_retries`. `[ollama]` section removed (same as Python's `parser.remove_section("ollama")`).

**Backup logic:** Timestamped `.bak` files with microsecond precision + counter suffix for collisions — identical to Python's `_backup()`. Rust implements civil-from-days algorithm manually instead of `datetime.now().strftime()`.

**Write logic:** Custom `IniDocument` (from `ini.rs`) instead of Python's `configparser.ConfigParser`; produces equivalent output: section/key order preserved, comments dropped, values written as `key = value`, blank line after each section. Atomic write via `.tmp` rename — identical to Python.

**Formatting:** `py_bool()` returns `"True"` / `"False"` (capitalized) matching Python's `str(bool)` output. `py_float()` uses Rust's `{:?}` Debug formatter which matches Python's `str(float)` for common magnitudes (`45.0`).

**Error formatting:** `format_validation_errors()` produces same bullet-list format as Python: `"Configuration errors:\n  \u{2022} ..."`.

## src/prompts.rs — Prompt ID constants only

Python reference: `forza/prompts.py` (67 lines) — defines `DEFAULT_PROMPT_ID`, `SYSTEM_PROMPTS` dict, prompt utility functions.

Status: **Partially ported** (intentional). Only `DEFAULT_PROMPT_ID = "user_header_shaped_v1"` + `PROMPT_IDS = &[DEFAULT_PROMPT_ID]` slice for validation in `lib.rs`.

**Not ported:** Full `SYSTEM_PROMPTS` dict with prompt text, plus all utility functions (`get_system_prompt`, `prompt_snapshot_payload`, `prompt_content_hash`, `prompt_snapshot_id`) — deferred to Fase 7 (LM Studio integration crate). Crate only needs valid IDs for `[prompt] active` validation.

## src/ini.rs — Ordered INI reader/writer

Python reference: Python's `configparser.ConfigParser` stdlib, used in `forza/config.py` + `forza/application/config_service.py`.

Status: **Ported**. Minimal ordered INI document reader/writer that mirrors observable behavior of Python's `configparser`:

**Structs:**
- `IniSection` — represents one section with keys in file order
- `IniDocument` — ordered collection of sections (mirrors dict-of-dicts but preserves insertion order)

**Methods:**
- `parse(text)` — parses INI text, preserving section/key order, dropping comments (`#`, `;`)
- `get(section, key)` — retrieves value
- `ensure_section(name)` — creates section if absent (mirrors `_ensure()` helper)
- `set(section, key, value)` — sets/updates key preserving position; appends new keys
- `remove_key(section, key)` — removes key when present
- `remove_section(name)` — removes entire section
- `render()` — serializes with configparser-compatible layout: `[section]\nkey = value\n` per line, blank line after each section block

**Differences:** Rust supports both `=` and `:` as key-value separators. No interpolation support (Python supports `%` interpolation but application doesn't use it). Comments dropped during parse (same as Python's configparser behavior).

## tests/config_contract.rs — Contract-level tests

Python reference: `forza/config.py` + `docs/contracts/configuration.md`.

Status: **Ported**. 6 test cases covering full config loading + validation pipeline:

1. `missing_file_yields_python_defaults()` — verifies missing INI produces all Python defaults; asserts every field matches exactly
2. `full_ini_overrides_every_section()` — complete INI with custom values loads correctly and validates
3. `invalid_values_warn_and_fall_back_leniently()` — lenient mode: invalid numerics fall back to defaults, strings taken as-is (e.g., `"bmp"` for image_format), warnings collected; then `validate_config` catches same issues
4. `strict_mode_fails_on_first_invalid_value()` — strict mode aborts on first error
5. `empty_optional_values_become_none()` — empty strings for optional fields (`context_length`, `reasoning_mode`) become `None`
6. `validation_collects_all_failures()` — deliberately invalid `AppConfig`; verifies all expected errors reported (image_format, reasoning_mode, prompt active, workers, timeouts, context_length, eval_batch_size, reload_streak, max_width, encode_quality, temp_min >= temp_max)

## Overall assessment

`forza-config` is **fully ported** for its scope. All data structures, defaults, parsing logic and value-level validations faithfully reproduced. Only gap: path-writability checks omitted in `validate_config`. `src/prompts.rs` partially ported intentionally (prompt text deferred to Fase 7). Rust Result-style error handling replaces Python's `ConfigSaveResult` dataclass; adds `gamertag_changed` tracking for purpose described in configuration contract.
