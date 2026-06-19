# Developer Maintenance Guide: 1. Project purpose

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: Developer maintenance guidance shard generated from the former oversized `guide.md` document
Last verified: 2026-06-15

Back to index: [`../guide.md`](../guide.md).

## 1. Project purpose

Forza Motorsport Results Extractor processes Forza Motorsport race-result screenshots with a local vision model, stores extracted state in SQLite, and produces operational views, CSV exports, and best-lap PDF reports.

The project is not a generic OCR wrapper. It has domain-specific correction, validation, review, and best-lap semantics for Forza race screenshots.

## 2. First local setup

Use Python 3.10 or newer.

```bash
python install.py
pip install -e .[dev,gui]
python -m forza maintenance db-upgrade
python -m forza maintenance db-doctor --json
python -m forza gui
```

A local LM Studio server must also be running. The project uses the native LM Studio REST API only; compatibility paths for OpenAI-style endpoints and Ollama were removed. Model values live in the `[lmstudio]` section of `forza_config.ini`, so runs can control model instance loading, context length, reasoning mode, image format, and response stats.

`json-repair` is a runtime dependency, not an optional feature. Model parsing should always use the same deterministic sequence: strict JSON parse first, then one `json_repair` pass, then an explicit parse error.

## 3. Validation before merging or releasing

Run the validation set from the repository root:

```bash
python -m compileall -q forza
python -m pytest -q
python -m pytest -q -W error::ResourceWarning
python -m pytest --cov=forza --cov-report=term-missing
python -m forza --help
python -m forza maintenance db-doctor --json
python -m forza --dry-run
python -m forza gui
```

Notes:

- Coverage is a risk signal, not a blind goal. Prioritize coverage for orchestration, persistence, config, parsing, and regression-prone GUI contracts.
- GUI tests are partly static by design. Do not rely only on them for behavior. Add behavioral tests when a workflow can be tested without a full Qt interaction harness.
- The repository may not have remote GitHub Actions checks. Absence of remote status is not equivalent to validation.
- Test profiles, marker taxonomy, coverage gates, and cleanup rules live in `docs/developer/testing-policy.md`; the active rollout plan lives in `docs/history/2026-06-13_testing_policy_implementation_plan_archive.md`.
- Detailed local test profiles, marker taxonomy, and test-debt cleanup rules live in `docs/developer/testing-policy.md`. Keep that policy current before deleting or reclassifying tests.

Versioning rules:

- `pyproject.toml` `[project].version` is the only version source of truth.
- `forza.version` exposes that version to GUI and package code.
- Release tags, changelog sections, and displayed GUI version must match.
- Follow `docs/contracts/versioning.md` before any release or version bump.

## 4. Runtime source of truth

The runtime database is `data/forza.sqlite3`.

Core rules:

- SQLite is the operational source of truth.
- Alembic owns schema migration.
- Normal CLI and GUI startup must not auto-run migrations.
- Schema upgrades must be explicit maintenance actions.
- Runtime source screenshots are not renamed, moved, or deleted by extraction.
- File rename, export, and selected asset deletion are explicit GUI actions.
- Image file paths are persisted and surfaced as strings; convert to `Path` only
  at filesystem operation boundaries.
- Raw decoder metadata in `image_metadata_json` is retained for analysis only,
  not as runtime source of truth.
- Legacy JSON snapshots and cache files are not runtime state.

Key SQL-backed concepts:

```text
image_files          observed physical screenshot files and file state
extraction_runs      run-level processing records, prompt/config counters, operational failures
run_inputs           every file considered by a run and its process/skip/duplicate decision
prompt_snapshots     immutable prompt text/hash evidence attached to runs/results
model_runtime_snapshots observed LM Studio preflight/recheck state
extraction_results   final per-image extraction summary
extraction_attempts  per-call retry/debug records, redacted request payloads, raw/parsed response
model_artifacts      hash/size tracked registered model artifacts
lap_records          extracted lap rows and persisted best-lap frontier
review_cases         human-review queue
image_flags          debug/image-management flags
export_artifacts     explicit export outputs
reference_tracks     SQL runtime track references seeded explicitly
reference_cars       SQL runtime car references seeded explicitly
external_record_imports external import snapshots and issue summaries
external_lap_records active/inactive external records
```

## 5. Main workflow

```text
data/input/*.png
  -> RunService
  -> ImageInventoryService
  -> ExtractionService
  -> pipeline.process_image
  -> LLMBackend
  -> run_inputs + image_files + extraction_results + extraction_attempts + model_artifacts + lap_records
  -> review_cases + image_flags
  -> RebuildService
  -> persisted best-lap frontier
  + external_lap_records
  -> Best Laps GUI + CSV/PDF exports
```

Important behavior:

- A run must fail if a model result cannot be persisted to SQLite.
- After image discovery, `RunService` records `run_inputs` for every considered
  file. Dry-run rows use `decision='skip'` with `skip_reason='dry_run'`.
- Before extraction, `RunService` performs an LM Studio preflight and records a
  `model_runtime_snapshots(snapshot_kind='preflight')` row when runtime
  diagnostic data is available. The preflight must enter `build_backend(cfg)` so
  the configured model is loaded and validated with the requested runtime
  parameters.
- If preflight fails, the run is marked failed as an operational backend error,
  a failed `run_finished` event is emitted, and no new image extraction errors
  are created for screenshots that were never submitted to chat.
- `ExtractionResult` must not be mutated by persistence services.
- CLI `run` must return non-zero for failed or cancelled runs.
- Main extraction concurrency is controlled by `[llm] workers`. Keep
  `workers = 1` as the safe LM Studio default unless local validation shows a
  higher value is stable for the selected model and hardware.
  Cancellation stops new work and prevents not-yet-checkpointed results from
  being persisted, but it does not force-kill an in-flight LLM request.
- Best Laps reads the persisted frontier. It must not invent an in-memory fallback as canonical output.
- Image race date is derived from the file modified timestamp, not Windows file creation time or empty `Date taken` metadata.
- Runtime IDs use UTC timestamp prefixes so logs, SQLite timestamps, and output directories can be correlated across time zones.

