Status: historical
Audience: developer, maintainer, LLM
Lifecycle: temporary (superseded by `migration_report.md` in this directory)
Scope: detailed porting analysis of `forza-rust/crates/forza-lmstudio` crate
Last verified: 2026-08-27
Supersedes: none

# Detailed porting analysis — forza-lmstudio

## Overview

LM Studio HTTP client, backend extraction loop, response parsing/validation, JSON repair, protocol types, load config compatibility checks. Ported from Python's `forza/lmstudio/` + `forza/pipeline/model_response.py`.

| File | Lines | Python Reference | Porting Status | Notes |
|------|-------|-----------------|----------------|-------|
| `src/lib.rs` | 91 | `__init__.py` + prompts | **Fully ported** | Adds embedded prompt via `include_str!`, hash identity test matches Python |
| `src/client.rs` | 340 | `client.py` | **Fully (core), Partially (diagnostic)** | Drops GUI summary fields from diagnostic; async instead of sync HTTP |
| `src/backend.rs` | 748 | `backend.py` | **Fully (loop), Partially (hooks)** | Drops threading locks, cooperative cancellation, persistence hooks; callback-based attempt recording |
| `src/response.rs` | 135 | `model_response.py` + `_semantic_retry_issues` | **Fully ported** | Adds brace-windowing fallback not in Python strict path |
| `src/json_repair.rs` | 109 | `backend.py` (`_parse_or_repair_response`) | **Fully (scope-limited)** | Intentionally narrower than Python's full `json_repair` library; documented scope decision |
| `src/protocol.rs` | 75 | `protocol.py` + `schemas.py` | **Fully (types), Partially (metadata)** | Drops `ModelRequestMetadata`, `ModelResponseStats` nested structs; flattens into record fields |
| `src/load_config.rs` | 121 | `load_config.py` | **Fully ported** | 1:1 port with typed structs instead of dicts |
| `src/error.rs` | 21 | `exceptions.py` + backend errors | **Fully ported** | Consolidates two Python error classes into single enum; uses `thiserror` |
| `examples/lm_health.rs` | 33 | (N/A) | **Rust-only** | New CLI smoke test utility |
| `tests/response_golden.rs` | 124 | (N/A) | **Rust-only** | New golden fixture test harness against 50+ real responses |

## src/lib.rs — Crate aggregate + public API surface

Python reference: `forza/lmstudio/__init__.py` + `forza/prompts.py` (system prompt retrieval).

Status: **Fully ported**. Module declarations for all sub-modules (`backend`, `client`, `error`, `json_repair`, `load_config`, `protocol`, `response`). Re-exported public types: `LMStudioBackend`, `RuntimeSnapshot`, `RuntimeClient`, `RuntimeModel`, `LlmError`, `AttemptStatus`, `ModelAttemptRecord`, `ModelExtractionResult`, `RequestKind`. The `prompts` submodule with prompt ID constants, system prompt text (via `include_str!`), and hash functions (`content_hash`, `payload_hash`, `snapshot_id`).

The Python equivalent is `forza/lmstudio/__init__.py` which re-exports the same types. The Rust version adds a `prompts` submodule that embeds the prompt text directly via `include_str!` (from `forza-rust/assets/prompt_user_header_shaped_v1.txt`). The hash functions (`payload_hash`, `snapshot_id`) are ported from Python's lifecycle service which uses `json.dumps(..., sort_keys=True, ensure_ascii=True)` — Rust replicates this with its own ASCII JSON serialization in `ascii_json_string`. A test asserts the hash matches the Python baseline exactly.

Key exported types/functions:
- `LMStudioBackend`, `RuntimeSnapshot` (from backend)
- `RuntimeClient`, `RuntimeModel` (from client)
- `LlmError` (from error)
- `AttemptStatus`, `RequestKind`, `ModelAttemptRecord`, `ModelExtractionResult` (from protocol)
- `prompts::DEFAULT_PROMPT_ID`, `prompts::USER_HEADER_SHAPED_V1`, `prompts::get_system_prompt()`, `prompts::payload_hash()`, `prompts::snapshot_id()`

## src/client.rs — LM Studio HTTP client + runtime diagnostics

Python reference: `forza/lmstudio/client.py`.

Status: **Fully ported (core logic), Partially ported (diagnostic fields)**. The core HTTP client logic (`list_models`, `health`) is fully ported. The URL normalization in `api_base()` matches Python's `_lmstudio_api_url` exactly. Model field extraction uses the same key aliases (`key`, `id`, `model_key`, `path`). Loaded instance parsing mirrors Python's `_loaded_instances()`.

The `runtime_status()` method is functionally equivalent but produces a simplified diagnostic: Rust drops several summary fields that Python computes for GUI display purposes (`runtime_config_summary`, `capabilities_summary`, `model_info_summary`, `errors` tuple). The warning logic (context_length mismatch, eval_batch_size mismatch, flash_attention mismatch, offload_kv_cache_to_gpu mismatch, vision capability check, max_context_length exceedance, reasoning mode mismatch) is identical.

Key exported types/functions:
- `LoadedInstance { id, config }`
- `RuntimeModel { id, path, display_name, publisher, architecture, format, params_string, size_bytes, max_context_length, quantization, selected_variant, capabilities, loaded_instances }`
- `RuntimeDiagnostic { level, ok, message, model_found, loaded, loaded_instances, instance_id, warnings }`
- `RuntimeClient::new()`, `list_models()`, `health()`, `runtime_status()`

## src/backend.rs — Extraction backend + adaptive retry loop

Python reference: `forza/lmstudio/backend.py`.

Status: **Fully ported (core extraction loop), Partially ported (persistence hooks)**. The full adaptive retry loop (`extract`) is ported with the same three retry tiers: transport failure -> JSON parse failure -> semantic validation failure. The attempt record construction mirrors Python's `_attempt_record()` method exactly, including all fields. Performance tracking (slow streak detection based on TPS floor and elapsed time) is identical.

Differences from Python:
- Rust uses `reqwest` async HTTP instead of synchronous `requests.Session`
- Rust drops the threading lock (`_model_lock`) that Python uses to serialize concurrent requests per model+endpoint
- Rust drops cooperative cancellation via `_CooperativeControl.checkpoint()` in backoff (Python's `_runtime_backoff` calls this)
- Rust drops `_reload_model()` method and the `__enter__/__exit__` context manager pattern
- Rust drops persistence hooks (`_on_attempt`, `_on_runtime_snapshot`) — instead uses a callback `on_attempt: &mut F` passed to `extract()`
- Rust drops `_capture_runtime_snapshot_if_changed()` and runtime observation signature tracking
- Rust's `output_text()` is slightly simplified (drops the `"type" == "message"` check that Python has)

The `ensure_loaded()` method is ported with the same compatible-instance search + POST `/models/load` fallback logic. The backoff helper (`runtime_backoff`) uses exponential backoff matching Python's formula: `min(0.5 * 2^(n-1), 4s)`.

Key exported types/functions:
- `BackendConfig { url, model, max_tokens, temperature, timeout_connect_secs, timeout_read_secs, max_retries, system_prompt, context_length, reasoning_mode }`
- `PerformancePolicy { tps_floor, reload_elapsed_s, reload_streak }` with `track()` method
- `RuntimeSnapshot { endpoint, configured_model, matched_model, loaded_model, instance_id, display_name, publisher, architecture, format, params_string, quantization, selected_variant, size_bytes, max_context_length, capabilities_json, desired_load_config_json, effective_load_config_json, health_ok, health_message, model_matches_config }`
- `LMStudioBackend::new()`, `extract()`, `ensure_loaded()`, `preflight_snapshot()`, `performance()`

## src/response.rs — Response parsing + validation + semantic retry issues

Python reference: `forza/pipeline/model_response.py` + `forza/lmstudio/backend.py` (`_semantic_retry_issues`).

Status: **Fully ported**. The response cleaning logic is identical. The Rust version adds a brace-windowing fallback (`extract_object`) that Python does not have in its strict parse path — this is an enhancement rather than a port gap (Python relies on `json_repair` for malformed cases). Validation checks are byte-for-byte equivalent: requires `"t"` field, requires `"e"` array, each entry must have `"dr"`, `"ca"`, `"cl"`, `"bl"`, and `"bl"` must parse as a valid lap time via `strip_dirty_symbol` + `parse_lap_time_ms`. The semantic retry issues logic is identical.

Key exported types/functions:
- `clean_json_content()`
- `parse_and_validate_response()`
- `validate_extracted_response()`
- `semantic_retry_issues()`

## src/json_repair.rs — Deterministic JSON repair pass

Python reference: `forza/lmstudio/backend.py` (`_parse_or_repair_response`) which calls the external `json_repair` Python library.

Status: **Fully ported (scope-limited)**. The module docs explicitly state the scope decision: real malformed fixtures fail on **validation**, not syntax. The Python code uses the third-party `json_repair` library which does a full repair pass then re-serializes. Rust implements only the observed syntax-level repairs (fences handled upstream, prose windowing, trailing commas, smart quotes). This is intentionally narrower scope — documented in Cargo.toml metadata notes and migration progress log.

Key exported types/functions:
- `repair_json()`

## src/protocol.rs — Protocol types + attempt/result structs

Python reference: `forza/lmstudio/protocol.py` + `forza/schemas.py` (`ModelExtractionAttempt`, `ModelRequestMetadata`, `ModelResponseStats`).

Status: **Fully ported (core types), Partially ported (metadata/stats structs)**. The protocol types are fully ported. However, Rust drops the richer metadata structures that Python has (`ModelRequestMetadata`, `ModelResponseStats`). In Python's `backend.py`, the returned `ModelExtractionResult` includes these structured objects; in Rust they are flattened into individual fields on `ModelAttemptRecord` (e.g., `input_tokens`, `output_tokens`, `tokens_per_second`, etc. are direct fields rather than nested structs). The Rust version also drops image metadata fields (`request_image_format`, `request_image_mime_type`, `request_image_width_px`, `request_image_height_px`, `request_image_bytes`) that Python's `_attempt_record` populates from `ModelRequestMetadata`.

Key exported types/functions:
- `LMSTUDIO_BACKEND_NAME` constant
- `AttemptStatus { Ok, Error }`
- `RequestKind { Initial, TransportRetry, JsonRetry, SemanticRetry }` with `as_str()`
- `ModelAttemptRecord` (25 fields)
- `ModelExtractionResult { parsed, raw_response, accepted_attempt, all_attempts }`

## src/load_config.rs — LM Studio load config compatibility checks

Python reference: `forza/lmstudio/load_config.py`.

Status: **Fully ported**. This is a 1:1 port. The Python file has identical logic, same alias lists, same uncomparable keys, same context_length satisfaction rule (>= rather than ==). Rust uses typed structs instead of Python dicts but the semantics are byte-for-byte equivalent. The only difference is that Rust's `NormalizedLoadConfig` is a struct with typed fields while Python returns a dict — this is an idiomatic adaptation, not a port gap.

Key exported types/functions:
- `UNCOMPARABLE_LOAD_CONFIG_KEYS` constant
- `DesiredLoadConfig { context_length, eval_batch_size, physical_batch_size, flash_attention, offload_kv_cache_to_gpu }`
- `NormalizedLoadConfig { context_length, eval_batch_size, physical_batch_size, flash_attention, offload_kv_cache_to_gpu }` (all Option-typed)
- `normalized_load_config()`
- `load_config_value_satisfies()`, `load_config_value_satisfies_bool()`
- `load_config_compatible()`

## src/error.rs — LLM error types

Python reference: `forza/exceptions.py` + `forza/lmstudio/backend.py` (`ExtractionAttemptsError`, `LMStudioRuntimeError`).

Status: **Fully ported (core error types)**. The Rust version consolidates Python's two LM Studio-specific errors (`ExtractionAttemptsError`, `LMStudioRuntimeError`) into a single `LlmError` enum. The `Exhausted` variant carries the attempt records (matching Python's `ExtractionAttemptsError.attempts`). The `Http` variant captures status codes. Rust uses `thiserror` for derive-based error formatting instead of Python class inheritance.

Key exported types/functions:
- `LlmError { Transport(String), Http{status: u16}, Runtime(String), Parse(String), Exhausted{attempts: Vec<ModelAttemptRecord>} }`

## examples/lm_health.rs — LM Studio health check CLI tool

Python reference: No direct equivalent — this is a Rust-only smoke test utility.

Status: **N/A (Rust-only addition)**. CLI tool that connects to an LM Studio instance, runs health check and runtime status diagnostic. Demonstrates usage of `RuntimeClient`, `DesiredLoadConfig`, `NormalizedLoadConfig`. Serves as a manual smoke test equivalent to what Python GUI tools use internally (`_lmstudio_status` in `developer_overview_worker.py`).

## tests/response_golden.rs — Golden fixture response validation

Python reference: No direct test file — the golden fixtures are stored as JSON files in `fixtures/model_responses/` and tested by Python's extraction pipeline.

Status: **N/A (Rust-only test harness)**. Loads all 50+ real LM Studio response fixtures from `fixtures/model_responses/`. Tests that every accepted/malformed fixture passes strict parse + validation. Verifies accepted fixtures match stored `parsed_json` exactly. Verifies semantic retry issues are empty for accepted fixtures. Tests synthetic corruptions (trailing commas, prose wrapping, markdown fences). This is a new Rust test that validates the response parsing against real-world golden fixtures. Python tests these responses through the full extraction pipeline rather than in isolation. The fixture format (`raw_response`, `parsed_json`, `kind`) matches what Python's backend produces.

## Key Porting Gaps Summary

1. **Threading/concurrency**: Rust drops Python's `_model_lock` serialization and cooperative cancellation (`_CooperativeControl.checkpoint()`). This is acceptable for single-threaded async usage but means concurrent access to the same backend requires external synchronization.

2. **Persistence hooks**: Python's `configure_persistence()` method with `_on_attempt`/`_on_runtime_snapshot` callbacks is replaced by a simpler `on_attempt: &mut F` callback passed directly to `extract()`. Runtime snapshot persistence is not implemented in Rust.

3. **Rich metadata structs**: Python returns nested `ModelRequestMetadata` and `ModelResponseStats` objects; Rust flattens these into individual fields on `ModelAttemptRecord`, dropping image metadata fields (`request_image_format`, etc.).

4. **Context manager pattern**: Python uses `__enter__/__exit__` for lifecycle management with `_ensure_loaded()` in `__post_init__`; Rust has no context manager, requiring manual `ensure_loaded()` calls.

5. **GUI summary fields**: The diagnostic struct drops several display-oriented fields (`runtime_config_summary`, `capabilities_summary`, `model_info_summary`, `errors`) that Python computes for the GUI developer overview panel.
