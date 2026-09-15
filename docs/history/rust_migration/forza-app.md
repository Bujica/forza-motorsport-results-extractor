Status: historical
Audience: developer, maintainer, LLM
Lifecycle: temporary (superseded by `migration_report.md` in this directory)
Scope: detailed porting analysis of `forza-rust/crates/forza-app` crate
Last verified: 2026-08-27
Supersedes: none

# Detailed porting analysis — forza-app

## Overview

Application services layer: extraction, rebuild, run control, settings, image inventory/detail/debug, review queue. Ported from Python's `forza/application/` + `forza/gui/controllers/` layers.

| File | Lines | Python Source | Status |
|------|-------|--------------|--------|
| `src/lib.rs` | 18 | N/A (crate aggregate) | **Ported** |
| `src/services/mod.rs` | 95 | Multiple modules | **Ported** |
| `src/services/image_inventory.rs` | 195 | `inventory.py`, `image_reads.py` | **Ported** |
| `src/services/image_detail.rs` | 45 | `image_reads.py`, `image_debug_reads.py` | **Ported** |
| `src/services/image_debug.rs` | 108 | `image_debug_reads.py` | **Ported** |
| `src/services/review_queue.rs` | 85 | `review_reads.py`, `review_service.py` | **Ported** |
| `src/services/rebuild.rs` | 39 | `rebuild_service.py` | **Partially ported** |
| `src/services/settings.rs` | 532 | `settings_controller.py` | **Ported** |
| `src/services/run_control.rs` | 72 | `run_control.py` | **Ported** |
| `src/services/extraction_runner.rs` | 818 | `run_service.py`, `extraction_service.py` | **Partially ported** |
| `src/services/extraction_replay.rs` | 246 | `process.py`, `response.py` | **Ported** |
| `tests/run_flow.rs` | 206 | N/A (new Rust test) | **New Rust test** |
| `tests/replay_pipeline.rs` | 252 | N/A (new Rust test) | **New Rust test** |
| `tests/extraction_runner.rs` | 169 | Python test suite | **New Rust test** |

## src/lib.rs — Crate aggregate + public API surface

Python reference: None directly — this is a Rust module-level re-export file with no Python equivalent. It serves as the crate's public API surface.

Status: **Rust-specific**. Re-exports all types and functions from `services` module, including `BestLapEntry`, `DoctorSummary`, `ImageDebugFilter`, `ImageDetailData`, `ImageInventoryEntry/Filter/Options/Service`, `RebuildOutcome`, `ReviewCaseEntry`, `RunControl/Event/Params`, `SettingRow/SettingsSnapshot`, and all service functions.

## src/services/mod.rs — Module aggregator + shared types

Python reference: Aggregates Python modules: `extraction_replay.py` / `extraction_service.py`, `image_debug_reads.py`, `image_reads.py`, `rebuild_service.py`, `review_reads.py` / `review_service.py`, `run_control.py`, `settings_controller.py`.

Status: **Ported (module aggregator)**. Rust module aggregator that re-exports all sub-modules and defines shared types. Key additions not in Python: `BestLapEntry` — thin projection of `ExportFlatRow` from `forza_db::repositories::laps`, used for the Best Laps GUI screen; `DoctorSummary` — wraps `forza_db::doctor::DoctorReport`.

## src/services/image_inventory.rs — Image inventory service + folder sync

Python reference: `forza/application/image/inventory.py` (`ImageInventoryService`, `scan_input_folder`) and `forza/application/gui_read/image_reads.py` (`GuiImageReadQueries`, `list_images`, `image_filter_values`).

Status: **Ported**. Key functions/types exported: `ImageInventoryEntry` — GUI row for the Images list (maps to Python's `GuiImage`); `ImageInventoryOptions` — tracks/runs dropdown options; `ImageInventoryFilter` — filter struct with file/processing/best_lap status, run_id, track filters; `ImageInventoryService::new()` / `database_file()` / `options()` / `list()` / `sync_input_folder()`.

**Notable differences:** Rust's `sync_input_folder` is explicitly documented as the GUI equivalent of Python's `scan_input_folder`. The Rust version uses raw SQL directly (no ORM), while Python uses SQLAlchemy + repositories. Rust does not track "refreshed" counts or "missing file" reconciliation that Python's `scan_input_folder` does.

## src/services/image_detail.rs — Image detail composite bundle

Python reference: `forza/application/gui_read/image_reads.py::get_image` and `forza/application/gui_read/image_debug_reads.py::get_image_debug_case`.

Status: **Ported**. Key functions/types exported: `ImageDetailData` — composite struct containing meta, laps, reviews, results, attempts for one image (maps to Python's `GuiImageDebugDetail`); `load_image_detail(conn, image_file_id)` — assembles the full detail bundle from multiple read queries.

**Notable differences:** Rust returns `Ok(None)` when the image is unknown; Python returns `None` directly. Rust does not include artifacts, runtime snapshots, raw_response, parsed_result_payload, or timeline that Python's `GuiImageDebugDetail` contains (those belong to Image Debug, not Image Detail).

## src/services/image_debug.rs — Image debug cases + detail loading

Python reference: `forza/application/gui_read/image_debug_reads.py` (`GuiImageDebugReadQueries`, `_matches_case`).

Status: **Ported**. Key functions/types exported: `ImageDebugFilter` — filter struct with status, backend, model, prompt_name, run_id fields; `list_debug_cases(conn, filter)` — lists debug cases with post-fetch in-memory filtering (mirrors Python's `_matches_case` logic); `load_debug_detail(conn, image_file_id, selected_result_id)` — maps to Python's `get_image_debug_case()`; `load_debug_detail_by_result(conn, extraction_result_id)` — maps to Python's `get_image_debug_case_by_result()`.

**Notable differences:** Rust fetches 500 rows then filters in-memory (Python does the same via `_matches_case` post-fetch). Rust has a unit test verifying filter passthrough for None/"all" values.

## src/services/review_queue.rs — Review queue + case decisions

Python reference: `forza/application/gui_read/review_reads.py::list_review_queue` and `forza/db/repositories/review_corrections.py` / `forza/db/repositories/reviews.py`.

Status: **Ported**. Key functions/types exported: `ReviewCaseEntry` — GUI row for review cases (maps to Python's `GuiReviewCase`, simplified); `list_review_cases(conn, bucket, image_file_id)` — lists cases filtered by open/resolved/all bucket with optional image narrowing; `decide_case(conn, case_number, field, value)` — applies operator decision via `apply_manual_correction`; `ignore_case(conn, case_number)` — sets status='ignored' for open cases.

**Notable differences:** Rust uses raw SQL directly; Python uses SQLAlchemy ORM. Rust's `list_review_cases` does not support pagination (limit/offset), reason/outcome/run_id filters that Python supports. Rust's `ReviewCaseEntry` is a simplified projection (fewer fields than Python's `GuiReviewCase`).

## src/services/rebuild.rs — Derived state rebuild pass

Python reference: `forza/application/rebuild_service.py::RebuildService.rebuild_derived_state`, `rebuild_outputs` and `forza/db/repositories/frontier.py` / `forza/db/repositories/laps.py`.

Status: **Partially ported**. Key functions/types exported: `RebuildOutcome` — counts of best_lap_winners, review_inserted/kept/auto_resolved; `rebuild(conn, gamertag)` — full rebuild pass: mark_best_laps → query_review_candidates → upsert_review_cases → update run-level counters.

**Notable differences:** Rust updates `extraction_runs.review_case_count` via raw SQL batch; Python uses `RunRepository.refresh_review_counts()`. Rust does not apply corrections (`ReviewCorrectionRepository.apply_all`) before rebuild like Python's `rebuild_derived_state` does — this is a behavioral difference, the Rust rebuild skips the correction application step.

## src/services/settings.rs — Settings snapshot + validation

Python reference: `forza/gui/controllers/settings_controller.py::SettingsController`, `_snapshot`, `_paths`, `_llm`, `_runtime`.

Status: **Ported**. Key functions/types exported: `SettingRow` — key, name, value, status (ok/invalid/missing/pending), editor type, options, group; `SettingsSnapshot` — rows, validation_ok, validation_message, dirty flag; `settings_snapshot(cfg, pending, dirty, validation_override)` — builds the snapshot applying pending edits on top; Group constants: `GROUP_PATHS`, `GROUP_LLM`, `GROUP_RUNTIME`.

**Notable differences:** Rust uses `forza_config::AppConfig` directly; Python uses `GuiConfigState` + `AppConfig`. Rust has helper functions for path status (`dir_status`, `parent_status`) that mirror Python's `_dir_status`, `_parent_status`. Rust includes `py_bool()` and `py_float()` helpers to match Python string formatting conventions (e.g., `"True"`/`"False"`, trailing `.0`). Rust has comprehensive unit tests verifying key ordering, pending overrides, validation override behavior, and path status.

## src/services/run_control.rs — Cooperative pause/cancel state

Python reference: `forza/application/run_control.py::RunControl`, `RunCancelled`.

Status: **Ported**. Key functions/types exported: `RunControl` — cooperative pause/cancel state with atomic bools; `new()` / `is_cancelled()` / `is_paused()` / `checkpoint()` / `request_cancel()`.

**Notable differences:** Python uses `threading.Event` + `Lock`; Rust uses `Arc<AtomicBool>` (more lightweight). Python tracks pause timing (`paused_duration_s`, `elapsed_since()`); Rust does not track pause duration. Python raises `RunCancelled` exception at checkpoints; Rust returns `bool` from `checkpoint()`. Rust's `is_paused()` explicitly excludes cancelled state: `paused && !cancelled` (same as Python).

## src/services/extraction_runner.rs — Full extraction pipeline + event dispatch

Python reference: `forza/application/run_service.py::RunService`, `_run_body` and `forza/application/extraction_service.py::ExtractionService`.

Status: **Partially ported**. Key functions/types exported: `RunEvent` — enum of Started/Plan/ImageStarted/ImageDone/Progress/Log/Finished/Failed events; `RunParams` — all parameters needed for a run, built from `AppConfig` via `from_config()`; `spawn_extraction(params, control, on_event)` — spawns extraction on dedicated thread with cooperative cancellation; `run_blocking()` / `run_async()` — the full pipeline: discovery → plan → encode → LM Studio → persist attempts/result/laps → run counters.

**Notable differences:** Rust uses a single-threaded tokio runtime inside the extraction thread; Python uses `ThreadPoolExecutor` for parallel workers. Rust does not support multi-worker parallel extraction (Python's `_process_parallel`). The Rust runner always processes sequentially (`workers: 1`). Rust implements its own `chrono_like_now()` for run ID generation (same format as Python's `utc_now().strftime("%Y%m%d_%H%M%S") + uuid4().hex[:8]` but without UUID suffix). Rust handles retry-errors mode with inline discovery logic matching Python's `_retry_error_discovery`. Rust includes preflight snapshot persistence and runtime snapshot recording. Rust does not implement abandoned run reconciliation (`reconcile_abandoned_runs`) or interrupted run recovery that Python has.

## src/services/extraction_replay.rs — Recorded response replay pipeline

Python reference: `forza/pipeline/process.py::process_image` and `forza/lmstudio/response.py::parse_and_validate_response`, `semantic_retry_issues`.

Status: **Ported**. Key functions/types exported: `to_attempt_insert(record, model)` — converts backend record to persistence primitive; `ReplayOutcome` — accepted flag, lap_rows count, attempt_row_ids; `replay_recorded_response(conn, run_id, image_file_id, extraction_result_id, raw_response, model)` — runs recorded response through full pipeline without LM Studio contact (Fase 7 acceptance criterion); `derive_and_insert_laps(conn, run_id, image_file_id, extraction_result_id, parsed, source_file)` — shared by replay and live extraction paths.

**Notable differences:** Rust uses raw SQL INSERT for lap records; Python uses SQLAlchemy ORM + repositories. Rust's `derive_and_insert_laps` mirrors Python's `process_image()` lap derivation logic: track normalization, weather normalization, race class detection, driver sanitization, dirty lap detection, best lap cleaning.

## Tests

| Test file | Purpose | Status |
|-----------|---------|--------|
| `tests/run_flow.rs` | Fase 8 e2e: replay → review → correction → rebuild without model contact | **New Rust test** |
| `tests/replay_pipeline.rs` | Fase 7 criterion with fixture files from `fixtures/model_responses/` | **New Rust test** |
| `tests/extraction_runner.rs` | Runner behavior tests (empty input, cancel, pause, retry) | **New Rust test** |

## Summary Table

| File | Python Reference(s) | Porting Status | Notes |
|------|---------------------|---------------|-------|
| `lib.rs` | N/A | Rust-specific | Public API re-export surface |
| `services/mod.rs` | Multiple modules | Fully ported | Module aggregator + shared types (BestLapEntry, DoctorSummary) |
| `image_inventory.rs` | `inventory.py`, `image_reads.py` | Fully ported | `sync_input_folder` mirrors Python's `scan_input_folder`; missing "refreshed/missing" counts |
| `image_detail.rs` | `image_reads.py`, `image_debug_reads.py` | Fully ported | Simplified detail bundle (no artifacts/runtime/raw_response) |
| `image_debug.rs` | `image_debug_reads.py` | Fully ported | Post-fetch in-memory filtering matches Python's `_matches_case` |
| `review_queue.rs` | `review_reads.py`, `review_service.py` | Fully ported | Simplified projection; no pagination/filtering support |
| `rebuild.rs` | `rebuild_service.py` | Partially ported | Skips correction application (`apply_all`) before rebuild |
| `settings.rs` | `settings_controller.py` | Fully ported | Comprehensive tests matching Python controller behavior |
| `run_control.rs` | `run_control.py` | Fully ported | AtomicBool vs Event; no pause duration tracking; bool return vs exception |
| `extraction_runner.rs` | `run_service.py`, `extraction_service.py` | Partially ported | No parallel workers, no abandoned run reconciliation, simplified run ID |
| `extraction_replay.rs` | `process.py`, `response.py` | Fully ported | Full pipeline replay without LM Studio; shared lap derivation |
| `tests/run_flow.rs` | N/A | New Rust test | Fase 8 e2e: process → review → correct → rebuild |
| `tests/replay_pipeline.rs` | N/A | New Rust test | Fase 7 criterion with fixture files |
| `tests/extraction_runner.rs` | Python test suite | New Rust test | Runner behavior tests (empty input, cancel, pause, retry) |

## Overall assessment

The crate is substantially ported. The two areas with partial coverage are:

1. **rebuild.rs**: Skips the correction application step that Python's `RebuildService.rebuild_derived_state` performs before recomputing best laps and review cases.
2. **extraction_runner.rs**: Does not support multi-worker parallel extraction (Python supports configurable workers), does not implement abandoned run reconciliation, and uses a simplified run ID format (no UUID suffix).
