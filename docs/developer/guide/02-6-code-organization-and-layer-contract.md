# Developer Maintenance Guide: 6. Code organization and layer contract

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: Developer maintenance guidance shard generated from the former oversized `guide.md` document
Last verified: 2026-06-14

Back to index: [`../guide.md`](../guide.md).

## 6. Code organization and layer contract

The reorganized package layout is part of the project contract. New features
should fit one of these packages before a new package or cross-layer dependency
is introduced.

User-facing GUI text, operator messages, logs, and project documentation should
use English unless a specific externally supplied value is being displayed.
Keep warning text explicit about configured values versus observed runtime
values.

High-level layout:

```text
forza/config.py                 config dataclasses, loading, validation
forza/cli/                      thin command adapters
forza/application/              application-level use cases and CLI orchestration
forza/domain/                   pure domain helpers
forza/db/                       SQLModel models, repositories, Alembic migration support
forza/gui/                      PySide6 GUI, controllers, views, workers, widgets, GUI read/write facades
forza/pipeline/                 image discovery, encoding, model-response parsing, image-to-result processing
forza/lmstudio/                 LM Studio native backend and runtime metadata client
forza/output/                   CSV and PDF writers
forza/domain/review_rules.py    pure review-detection helper rules
tests/                          unit, regression, static-contract, and integration tests
docs/                           architecture and remediation documentation
```

### 6a. Package responsibilities

`forza/domain/`

- Owns pure domain logic: lap parsing, dirty-lap detection, class ordering,
  track/car normalization, review-rule helpers, and string normalization.
- Must not import GUI, SQLModel sessions, repositories, LM Studio, CLI, or
  filesystem-heavy application services.
- May define deterministic helpers used by any other layer.

`forza/schemas/`

- Owns public DTOs/enums passed across package boundaries.
- `ExportLap` is the SQL-native flat row for CSV/PDF/lab ground truth.
- `ExtractionResult` is the in-memory pipeline result for one image file.
- Avoid adding persistence-only SQL details here unless multiple layers need
  the same shape.

`forza/db/`

- Owns SQLModel entities, repositories, Alembic migrations, and schema-state
  helpers.
- Repositories should express persistence operations, not GUI workflows.
- Application, GUI read/write facades, and lab services may use DB helpers;
  domain and output must not open DB sessions.

`forza/pipeline/`

- Owns image discovery, duplicate planning, request-image encoding,
  model-response parsing, and `process_image`.
- `process_image` may call the LM Studio backend interface and pure domain
  normalization, but it must not persist to SQLite or write reports.
- Shared image discovery lives in `forza.pipeline.image.find_images`; do not
  add duplicate image-discovery helpers elsewhere.

`forza/lmstudio/`

- Owns the native LM Studio REST backend, model runtime metadata client,
  model load/unload behavior, retries, response stats, and SQL-attempt payload
  production.
- Other layers should use `build_backend(cfg)` or `LMStudioRuntimeClient`
  rather than constructing raw requests directly.
- Do not reintroduce OpenAI-compatible, Ollama, or generic backend branches
  without updating section 7b and the related tests.

`forza/output/`

- Owns CSV/PDF rendering.
- Takes already-normalized data (`ExportLap`, external records, config,
  ordered track lists) and writes artifacts.
- Must not query SQLite, call LM Studio, discover images, or mutate review
  state.

`forza/application/`

- Owns use cases that coordinate DB, pipeline, LM Studio, output, config, and
  explicit maintenance behavior.
- This is the primary place for orchestration: runs, extraction batches,
  rebuilds, exports, DB doctor, image inventory/rename/export, external-record
  import, and Best Laps reads.
- Application services may use repositories and package APIs, but should expose
  stable public methods to CLI and GUI.
- `RunService` is the top-level run orchestrator used by CLI and GUI flows.
  `RunLifecycleService` is the database persistence boundary for run state
  changes such as begin, complete, fail, preflight failure, and recovery.

`forza/gui/`

- Owns PySide6 UI code, controllers, workers, widgets, and GUI-only DTO/read
  facades.
- `GuiReadService` and `GuiWriteService` are GUI facades. Controllers and views
  must use those facades or `forza.application` use cases.
- GUI views/controllers must not import repositories or open SQLModel sessions.
- Long-running work belongs in workers; views emit user-intent signals and do
  not perform persistence.


`forza/cli/`

- Owns argument parsing and command dispatch only.
- CLI commands load config, setup logging, then delegate to application
  services. Lab workflows are exposed through the GUI, not the public CLI.
- Do not put business logic, DB queries, or direct LM Studio calls in CLI
  modules.

### 6b. Dependency direction

Allowed dependency direction:

```text
cli -> application
gui -> application/gui facades
application -> db/domain/pipeline/lmstudio/output
pipeline -> domain/lmstudio schemas
lmstudio -> pipeline.model_response/domain schemas
output -> domain/schemas
db -> schemas/domain only when needed
domain -> standard library only
```

Keep dependencies acyclic where practical. If a new import creates a cycle,
move the shared type/helper into `schemas` or `domain`, or move the
orchestration upward into `application`.

### 6c. Public entry points

Prefer package public APIs when crossing layers:

```python
from forza.application import DatabaseService, RunService, RebuildService, ExportService
from forza.application import ExternalRecordService, ImageInventoryService, ImageRenameService
from forza.gui import GuiReadService, GuiWriteService
from forza.lmstudio import build_backend, LMStudioRuntimeClient
from forza.output import export_csv, generate_pdf
from forza.pipeline import find_images, plan_images, process_image
from forza.domain import load_reference_data, ordered_lap_key
```

Direct submodule imports are acceptable inside a package or in tests that need a
specific implementation detail. For feature code, prefer the public package
exports above unless there is a clear reason not to.

### 6d. Boundary rules

- GUI controllers and views use public services and application use cases.
- GUI code must not open SQLModel sessions directly.
- GUI code must not import repositories directly.
- CLI modules should stay thin and delegate real behavior to services/use cases.
- SQL-native exports use flat `ExportLap` rows, not grouped legacy `ExtractionResult` snapshots.
- Review detection helpers that are independent of SQL belong in `forza.domain.review_rules`; review-case persistence belongs in SQL repositories/application services.
- Domain helpers should stay free of GUI, SQL, LM Studio, and filesystem side effects.
- Normal extraction does not move, rename, or delete source screenshots; only explicit image-management actions may mutate files.
- Runtime source of truth is SQLite, not JSON snapshots or cache files.

### 6e. Where new code should go

Use this decision table before adding files:

```text
Pure parsing, ordering, normalization, domain scoring     -> forza/domain/
Cross-layer DTO or enum                                   -> forza/schemas/
SQL model, repository, migration, schema state             -> forza/db/
Image discovery/encoding or model-response validation      -> forza/pipeline/
LM Studio request, model runtime, retry, raw response       -> forza/lmstudio/
CSV/PDF rendering                                          -> forza/output/
Run/rebuild/export/import/inventory orchestration          -> forza/application/
GUI controller/view/worker/read-write facade               -> forza/gui/
Former lab/bench workflows                                -> do not reintroduce into runtime package
Argument parser or command adapter                         -> forza/cli/
```

If the feature seems to need logic in three or more layers, implement the
workflow in `application` and keep the lower layers focused on their own
contracts.

### 6f. Anti-patterns to avoid

- Recreating removed root modules such as `forza.pipeline.py`,
  `forza.extractor.py`, `forza.report.py`, or a new `forza.services` facade.
- Adding compatibility aliases for old module paths.
- Reading normalized external-record JSON files directly from Best Laps or PDF paths;
  community records are SQL-backed active state.
- Adding a second image finder, second JSON parser, or second LM Studio client.
- Letting GUI views write config files, database rows, or filesystem assets
  directly.
- Letting output writers query SQLite or recompute best laps.
- Treating partial driver lists as model failure in retry logic.

## 7. Configuration model

`forza.config.AppConfig` is the loaded runtime config. It includes path fields, user fields, LLM settings, image encoding settings, validation settings, PDF settings, and prompt selection.

Important config rules:

- Use `load_config(..., strict=True)` before operations where invalid typed values must fail rather than silently falling back.
- GUI writes and previews go through `ConfigFileService` via `GuiConfigState`, not through ad hoc INI edits.
- Saving config validates the candidate config, creates a timestamped backup, writes a temporary file, then replaces the target file.
- `[lmstudio]` is the only model section. Do not reintroduce backend switching or compatibility-only fields.
- Obsolete fields such as `output_dir` and `max_parse_retries` must not be reintroduced into `AppConfig` or GUI settings.
- `llm.image_format` supports `png`, `jpeg`, and `webp`; image file format belongs to `image_files`, while request payload format belongs to `extraction_results`.
- `llm.workers` controls extraction concurrency. Keep the default conservative
  for LM Studio unless the loaded model and hardware have been validated with
  parallel image requests.
- `llm.context_length`, `llm.reasoning_mode`, batch settings, KV-cache settings, image format, and performance watchdog settings are user-editable LM Studio controls.
- `llm.reasoning_mode` accepts `off`, `on`, `auto`, `low`, `medium`, and
  `high`; not every model advertises every mode through LM Studio.
- `llm.context_length = 5000` is the current safe default for Qwen3.5 9B with the production prompt and `reasoning_mode = off`. Re-evaluate the margin before enabling thinking/reasoning models or longer prompts.
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

For performance degradation, prefer a watchdog over routine unload/reload. The native backend schedules reload only after repeated slow responses, using `performance_tps_floor`, `performance_reload_elapsed_s`, and `performance_reload_streak`.

