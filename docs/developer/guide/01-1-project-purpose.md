Implementation: Rust (forza-rust/) — current. Legacy Python (forza/) frozen at 0.21.0-beta.1.

# Developer Maintenance Guide: 1. Project purpose

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: Developer maintenance guidance shard generated from the former oversized `guide.md` document
Last verified: 2026-09-05

Back to index: [`../guide.md`](../guide.md).

## 1. Project purpose

Forza Motorsport Results Extractor processes Forza Motorsport race-result screenshots with a local vision model, stores extracted state in SQLite, and produces operational views, CSV exports, and best-lap PDF reports.

The project is not a generic OCR wrapper. It has domain-specific correction, validation, review, and best-lap semantics for Forza race screenshots.

## 2. First local setup

Install the Rust toolchain, then build from `forza-rust/`:

```bash
cd forza-rust
cargo build -p forza-cli -p forza-gui
./target/debug/forza maintenance db-upgrade
./target/debug/forza maintenance db-doctor --json
./target/debug/forza gui
```

This produces `forza.exe` (CLI, clap arg parsing) and `forza-gui.exe` (Slint
UI). CLI commands: `forza.exe run [--dry-run|--force|--retry-errors|--limit N]
| rebuild | export [--out PATH] [--pdf] | config-check | gui | maintenance
<db-status|db-doctor|db-upgrade|db-reset|db-heal>`.

A local LM Studio server must also be running. The project uses the native LM Studio REST API only (reqwest+tokio HTTP backend in `forza-lmstudio`); compatibility paths for OpenAI-style endpoints and Ollama were removed. Model values live in the `[lmstudio]` section of `forza_config.ini`, loaded and validated by the `forza-config` crate (`load_config`, `validate_config`).

Model-response parsing, validation, and repair live in Rust too
(`forza-lmstudio::response` strict parse+validation plus
`forza-lmstudio::json_repair::repair_json`, used by the backend), keeping the
deterministic strict-parse-then-repair behavior.

## 3. Validation before merging or releasing

Run the validation set from `forza-rust/`:

```bash
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings
cargo fmt --all --check
./target/debug/forza --help
./target/debug/forza maintenance db-doctor --json
./target/debug/forza run --dry-run
./target/debug/forza gui
```

Fixtures live in `forza-rust/fixtures/`: `expected/` is committed;
`model_responses/` + `images/` are git-ignored personal data.

Notes:

- Coverage is a risk signal, not a blind goal. Prioritize coverage for orchestration, persistence, config, parsing, and regression-prone GUI contracts.
- GUI tests are partly static by design. Do not rely only on them for behavior. Add behavioral tests when a workflow can be tested without a full UI interaction harness.
- The repository may not have remote GitHub Actions checks. Absence of remote status is not equivalent to validation.
- Test profiles, marker taxonomy, coverage gates, and cleanup rules live in `docs/developer/testing-policy.md`; the original rollout plan was internal pre-beta evidence and is not published.
- Detailed local test profiles, marker taxonomy, and test-debt cleanup rules live in `docs/developer/testing-policy.md`. Keep that policy current before deleting or reclassifying tests.

Versioning rules:

- Workspace `Cargo.toml` `[workspace.package].version` (`0.1.0`) is the only version source of truth.
- `forza-app::APP_VERSION` exposes that version (plus git hash/build time) to CLI and GUI code, and every run row carries it.
- `forza.exe --version`, the GUI title, run rows, release tags, and changelog sections must match.
- Follow `docs/contracts/versioning.md` before any release or version bump.

## 4. Runtime source of truth

The runtime database defaults to `data/forza.sqlite3`.

Core rules:

- SQLite is the operational source of truth.
- Schema version is tracked via `PRAGMA user_version` (`SCHEMA_VERSION = 2`); `migration::upgrade()` in `forza-db` builds the schema from zero or applies pending migrations.
- Normal CLI and GUI startup must not auto-run migrations (the GUI errors and points at `maintenance db-upgrade` when the database is missing).
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
review_corrections   persisted human decisions applied by rebuild
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
  -> RunParams / spawn_extraction
  -> image inventory
  -> extraction_runner (sequential or multi-worker with pre-allocated inputs)
  -> forza-pipeline + forza-lmstudio backend
  -> run_inputs + image_files + extraction_results + extraction_attempts + model_artifacts + lap_records
  -> review_cases + image_flags
  -> rebuild()
  -> persisted best-lap frontier
  + external_lap_records
  -> Best Laps GUI + CSV/PDF exports
```

Important behavior:

- A run must fail if a model result cannot be persisted to SQLite.
- After image discovery, the runner records `run_inputs` for every considered
  file. `--dry-run` persists nothing: it only prints the discovery plan, with
  no LM Studio calls.
- Before extraction, the runner performs an LM Studio preflight and records a
  `model_runtime_snapshots(snapshot_kind='preflight')` row when runtime
  diagnostic data is available. The preflight must load and validate the
  configured model with the requested runtime parameters through the native
  backend.
- If preflight fails, the run is marked failed as an operational backend error,
  a failed `RunEvent::Failed` is emitted, and no new image extraction errors
  are created for screenshots that were never submitted to chat.
- CLI `run` must return non-zero for failed runs, and exit 130 for cancelled runs.
- Main extraction concurrency is controlled by the `workers` setting. Keep
  `workers = 1` as the safe LM Studio default unless local validation shows a
  higher value is stable for the selected model and hardware.
  Cancellation stops new work and prevents not-yet-checkpointed results from
  being persisted, but it does not force-kill an in-flight LLM request.
- The end of every run calls `rebuild()`: best laps (`mark_best_laps`) +
  review cases + system review flags (`sync_review_flags`) + per-run counters.
- Best Laps reads the persisted frontier. It must not invent an in-memory fallback as canonical output.
- Image race date is derived from the file modified timestamp, not Windows file creation time or empty `Date taken` metadata.
- Runtime IDs use UTC timestamp prefixes so logs, SQLite timestamps, and output directories can be correlated across time zones.

