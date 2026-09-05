Implementation: Rust (forza-rust/) — current. Legacy Python (forza/) frozen at 0.21.0-beta.1.

# Developer Maintenance Guide: 6. Code organization and layer contract

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: Developer maintenance guidance shard generated from the former oversized `guide.md` document
Last verified: 2026-09-05

Back to index: [`../guide.md`](../guide.md).

## 6. Code organization and layer contract

The workspace crate layout is part of the project contract. New features
should fit one of these crates before a new crate or cross-layer dependency
is introduced. The workspace is `forza-rust/` (version `0.1.0`); binaries are
`forza.exe` (`forza-cli`) and `forza-gui.exe` (`forza-gui`).

User-facing GUI text, operator messages, logs, and project documentation should
use English unless a specific externally supplied value is being displayed.
Keep warning text explicit about configured values versus observed runtime
values.

High-level layout:

```text
forza-rust/crates/forza-config/     config structs, loading (load_config), validation (validate_config)
forza-rust/crates/forza-cli/        thin clap command adapters (forza.exe)
forza-rust/crates/forza-app/        application-level use cases and CLI/GUI orchestration
forza-rust/crates/forza-domain/     pure domain helpers (lap/frontier/review_rules/normalizer/ordering/race_class)
forza-rust/crates/forza-db/         rusqlite schema DDL, repositories, migration::upgrade(), PRAGMA user_version state
forza-rust/crates/forza-gui/        Slint UI (ui/pages/*.slint), callbacks/state (lib.rs), worker (worker.rs),
                                    detail views, ui_state, ui_persist
forza-rust/crates/forza-pipeline/   image discovery, planning, hashing, metadata, encoding, naming,
                                    model-response intake helpers
forza-rust/crates/forza-lmstudio/   LM Studio native backend (reqwest+tokio), DesiredLoadConfig,
                                    PerformancePolicy, response parsing/validation/repair
forza-rust/crates/forza-output/     CSV (BOM+CRLF) and dependency-free PDF writer (TOC links)
forza-rust/fixtures/                expected/ committed; model_responses/ + images/ git-ignored personal data
docs/                               architecture and remediation documentation
```

### 6a. Crate responsibilities

`forza-domain/`

- Owns pure domain logic: lap parsing, dirty-lap detection, class ordering,
  track/car normalization, review-rule helpers, and string normalization.
- Only third-party text dependencies (regex/unicode crates); must not gain
  GUI, DB, LM Studio, CLI, or filesystem-orchestration dependencies.
- May define deterministic helpers used by any other layer.

There is no shared schemas package: each crate owns its row/param structs
(e.g. `forza-output::csv::ExportRow`, `forza-app::BestLapRow`, `RunParams`,
`SettingRow`/`SettingsSnapshot`) and orchestration passes owned data across
the boundary. Avoid adding persistence-only SQL details to shared shapes
unless multiple layers need the same shape.

`forza-db/`

- Owns rusqlite schema DDL, repositories, `migration::upgrade()`, and
  schema-state helpers (`schema_status`, `PRAGMA user_version`,
  `SCHEMA_VERSION = 2`).
- Repositories should express persistence operations, not GUI workflows
  (`best_laps::mark_best_laps`, `reviews`, `corrections::apply_all`,
  `flags::sync_review_flags`, `images`, `laps`, `runs`, `external_records`).
- The doctor battery `doctor::run_full_doctor` (~70 checks) lives here.
- Application and GUI read/write services may use DB helpers;
  domain and output must not open DB connections.

`forza-pipeline/`

- Owns image discovery (`discovery::find_images`), duplicate planning
  (`planning::plan_images`), hashing (`hashing::file_hash`), metadata,
  request-image encoding, naming, and model-response intake helpers.
- Only third-party dependencies (image/walkdir/sha2/chrono/etc.); it is a
  leaf the application layer wires together with the backend and the DB.
- Shared image discovery lives in `discovery::find_images`; do not
  add duplicate image-discovery helpers elsewhere.

`forza-lmstudio/`

- Owns the native LM Studio REST backend (`backend::LMStudioBackend`,
  reqwest+tokio), model runtime client (`client::RuntimeClient`), model
  load/unload behavior (`load_config::DesiredLoadConfig`), retries, response
  stats, strict response parse+validation (`response`), and JSON repair
  (`json_repair::repair_json`).
- Performance watchdog state uses `backend::PerformancePolicy` (defaults
  20.0 tok/s floor, 45.0 s elapsed, streak 3).
- Other layers should go through the backend/runtime client rather than
  constructing raw requests directly.
- Do not reintroduce OpenAI-compatible, Ollama, or generic backend branches
  without updating section 7b and the related tests.

`forza-output/`

- Owns CSV/PDF rendering (`csv::export_csv` / `csv::ExportRow`,
  `build_pdf_plan_ext`, `render_pdf`, `PdfRenderOptions`).
- Takes already-normalized data (`ExportRow`, external records, config,
  ordered track lists) and writes artifacts.
- Must not query SQLite, call LM Studio, discover images, or mutate review
  state.

`forza-app/`

- Owns use cases that coordinate DB, pipeline, LM Studio, output, config, and
  explicit maintenance behavior.
- This is the primary place for orchestration: runs (`services::extraction_runner`
  via `spawn_extraction` with `RunParams`/`RunControl`/`RunEvent`), rebuilds
  (`services::rebuild::rebuild` with `RebuildOutcome`), exports, DB doctor,
  image inventory/rename/export, external-record import, and Best Laps reads.
- `rebuild()` order matters: apply persisted corrections
  (`corrections::apply_all`) -> recompute frontier (`mark_best_laps`) ->
  refresh review candidates (`upsert_review_cases`, preserving
  operator-resolved cases by business key) -> sync system flags
  (`sync_review_flags`) -> per-run review counters.
- Application services may use repositories and crate APIs, but should expose
  stable public functions to CLI and GUI.

`forza-gui/`

- Owns the Slint UI: pages in `ui/pages/*.slint` (images/process/review/
  best-laps/diagnostics/settings/logs plus embedded image-detail/image-debug;
  NO Records page), callbacks and screen state in `src/lib.rs`, background
  work in `src/worker.rs`, `src/detail_views.rs`, `src/ui_state.rs`, and
  `src/ui_persist.rs`.
- GUI code must not perform persistence inline on the UI thread; a long-lived
  worker thread handles each request on its own short-lived thread and
  responses marshal back via `slint::invoke_from_event_loop`.
- Long-running work belongs to worker requests; callbacks enqueue requests
  and apply responses, they do not perform persistence inline.


`forza-cli/` and `forza-config/`

- `forza-cli` owns clap argument parsing and command dispatch only
  (`run | rebuild | export | config-check | gui | maintenance ...`).
- CLI commands load config, then delegate to application services or the GUI
  entry point. Lab workflows are exposed through the GUI, not the public CLI.
- Do not put business logic, DB queries, or direct LM Studio calls in CLI
  modules.
- `forza-config` owns `forza_config.ini` loading (`load_config`) and
  validation (`validate_config`); settings UI rows live in
  `forza-app/src/services/settings.rs` (`SettingRow`, `settings_snapshot`).

### 6b. Dependency direction

Cargo-verified edges (orchestration flows upward into `forza-app`):

```text
forza-cli -> forza-app/forza-gui/forza-db/forza-config/forza-output/forza-pipeline
forza-gui -> forza-app/forza-db/forza-config/forza-domain/forza-output/forza-pipeline
forza-app -> forza-db/forza-domain/forza-pipeline/forza-lmstudio/forza-output/forza-config
forza-domain, forza-pipeline -> third-party crates only (leaves; app wires them together)
forza-domain -> must stay free of GUI, DB, LM Studio, CLI, and filesystem orchestration
```

Keep dependencies acyclic where practical. If a new import creates a cycle,
move the shared type/helper into `forza-domain`, or move the
orchestration upward into `forza-app`.

### 6c. Public entry points

Prefer crate public APIs when crossing layers:

```rust
use forza_app::{rebuild, spawn_extraction, RunParams, settings_snapshot, SettingRow};
use forza_app::{apply_filters, filter_options, list_best_laps};
use forza_config::{load_config, validate_config};
use forza_db::migration::{schema_status, upgrade};
use forza_db::repositories::{mark_best_laps, sync_review_flags};
use forza_lmstudio::backend::{LMStudioBackend, PerformancePolicy};
use forza_lmstudio::load_config::DesiredLoadConfig;
use forza_output::csv::{export_csv, ExportRow};
use forza_output::{build_pdf_plan_ext, render_pdf, PdfRenderOptions};
use forza_pipeline::{find_images, plan_images, file_hash};
use forza_domain::ordering::ordered_lap_key;
use forza_domain::review_rules::*;
```

Direct submodule imports are acceptable inside a crate or in tests that need a
specific implementation detail. For feature code, prefer the public crate
exports above unless there is a clear reason not to.

### 6d. Boundary rules

- GUI callbacks use worker requests, public services, and application use cases.
- GUI code must not perform persistence inline on the UI thread.
- CLI modules should stay thin and delegate real behavior to services/use cases.
- SQL-native exports use flat `ExportRow` rows, not grouped legacy snapshots.
- Review detection helpers that are independent of SQL belong in `forza-domain::review_rules`; review-case persistence belongs in SQL repositories/application services.
- Domain helpers should stay free of GUI, SQL, LM Studio, and filesystem side effects.
- Normal extraction does not move, rename, or delete source screenshots; only explicit image-management actions may mutate files.
- Runtime source of truth is SQLite, not JSON snapshots or cache files.

### 6e. Where new code should go

Use this decision table before adding files:

```text
Pure parsing, ordering, normalization, domain scoring     -> forza-domain/
SQL schema DDL, repository, migration, schema state       -> forza-db/
Image discovery/planning/hashing/encoding/naming         -> forza-pipeline/
LM Studio request, model runtime, retry, raw response     -> forza-lmstudio/
CSV/PDF rendering                                          -> forza-output/
Run/rebuild/export/import/inventory orchestration          -> forza-app/
Slint page/callback/worker/detail-view/UI state            -> forza-gui/
Argument parser or command adapter                         -> forza-cli/
Config struct, loading, validation                         -> forza-config/
Former lab/bench workflows                                -> do not reintroduce into runtime crates
```

If the feature seems to need logic in three or more layers, implement the
workflow in `forza-app` and keep the lower layers focused on their own
contracts.

### 6f. Anti-patterns to avoid

- Recreating removed Python-era structures (compat shims, service facades,
  second JSON parsers, second LM Studio clients, second image finders).
- Reading normalized external-record JSON files directly from Best Laps or PDF paths;
  community records are SQL-backed active state.
- Letting GUI callbacks write config files, database rows, or filesystem assets
  directly instead of going through worker requests/services.
- Letting output writers query SQLite or recompute best laps.
- Treating partial driver lists as model failure in retry logic.

## 7. Configuration model

`AppConfig` (in `forza-config`) is the loaded runtime config. It includes path fields, user fields, LLM settings, image encoding settings, validation settings, PDF settings, and prompt selection.

Important config rules:

- Use `load_config(path, strict)` with `strict=true` before operations where invalid typed values must fail rather than silently falling back (the CLI also exposes `--strict`).
- GUI settings reads go through `settings_snapshot` (`SettingRow`/`SettingsSnapshot`); saves go through the worker `SaveSettings` request against the worker-owned live `AppConfig`, not through ad hoc INI edits.
- `[lmstudio]` is the only model section. Do not reintroduce backend switching or compatibility-only fields.
- Obsolete Python-era fields must not be reintroduced into `AppConfig` or GUI settings.
- `workers` controls extraction concurrency (`RunParams.workers`; multi-worker
  when > 1). Keep the default conservative for LM Studio unless the loaded
  model and hardware have been validated with parallel image requests.
- `context_length`, `reasoning_mode`, batch settings, KV-cache settings, image format, and performance watchdog settings are user-editable LM Studio controls surfaced through the settings rows.
- `extraction_results` stores the accepted/final per-image summary;
  `extraction_attempts` stores each concrete call, including rejected retries,
  redacted request payload, request hash, raw response, parse error,
  validation issues, resolved `model_instance_id`, and timing/token stats.
- Accepted raw response files are registered in `model_artifacts` with
  `sha256`, `size_bytes`, and `is_canonical=true`.

## 7a. Adaptive extraction retries

`max_retries` is a budget for different recovery actions, not repeated identical calls.

- `initial`: normal native LM Studio call.
- `transport_retry`: connection, timeout, HTTP, or model runner failure. The native backend reloads the model before retrying when appropriate.
- `json_retry`: invalid JSON or schema break. The retry adds a stricter "JSON only" instruction.
- `semantic_retry`: critical extraction failure such as an empty track, empty entry list, or all null best-lap values. Partial driver lists and missing specific drivers are valid and must not trigger retry.
- Accepted attempts are marked in SQL with `accepted = true`. Failed attempts remain queryable for model/prompt diagnostics.

For performance degradation, prefer a watchdog over routine unload/reload. The native backend schedules reload only after repeated slow responses, using `PerformancePolicy` (defaults 20.0 tok/s floor, 45.0 s elapsed, streak 3).

