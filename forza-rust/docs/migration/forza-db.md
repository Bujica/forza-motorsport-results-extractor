Status: historical
Audience: developer, maintainer, LLM
Lifecycle: temporary (superseded by `migration_report.md` in this directory)
Scope: detailed porting analysis of `forza-rust/crates/forza-db` crate
Last verified: 2026-08-27
Supersedes: none
Related tests: 6 test files (`connection_contract`, `schema_lifecycle`, `constraints`, `gui_inventory`, `doctor_basic`, `retry_selection`)

# Detailed porting analysis — forza-db

## Overview

SQLite schema, migrations, connections, queries and repositories. Ported from Python's `forza/db/` + `forza/application/gui_read/`. Abandons SQLModel/Alembic; uses raw SQL via rusqlite + r2d2_sqlite pool.

| File | Lines | Python Source | Status |
|------|-------|--------------|--------|
| `src/lib.rs` | 40 | N/A (crate aggregate) | **Ported** |
| `src/connection.rs` | 45 | `forza/db/session.py` | **Ported** |
| `src/schema_ddl.rs` | 582 | SQLModel entities + Alembic baseline | **Ported** |
| `src/migration.rs` | 95 | `forza/db/migrate.py` | **Ported** |
| `src/entities.rs` | N/A (does not exist) | N/A | **N/A** |
| `src/error.rs` | 43 | Python RuntimeError patterns | **Ported (+)** |
| `src/doctor.rs` | 108 | `forza/application/db_doctor/` | **Partially ported** |
| `src/gui_queries.rs` | 159 | `forza/application/gui_read/image_reads.py` | **Ported** |
| `src/image_detail.rs` | 277 | `forza/application/gui_read/` detail queries | **Ported** |
| `src/image_debug.rs` | 616 | `forza/application/gui_read/image_debug_reads.py` | **Ported** |
| `repositories/mod.rs` | 122 | Python repo aggregate + testing.py | **Ported** |
| `repositories/images.rs` | 102 | `forza/db/repositories/images.py` | **Partially ported** |
| `repositories/laps.rs` | 118 | `forza/db/repositories/laps.py` | **Partially ported** |
| `repositories/runs.rs` | 524 | Python runs/input/result pipeline | **Ported** |
| `repositories/reviews.rs` | 299 | `laps.py` + reviews.py + review_identity.py | **Ported** |
| `repositories/corrections.rs` | 113 | `forza/db/repositories/review_corrections.py` | **Ported** |
| `repositories/best_laps.rs` | 195 | `laps.py::mark_best_laps()` + frontier.py | **Ported** |
| `tests/connection_contract.rs` | 57 | session.py pragma tests | **Ported** |
| `tests/schema_lifecycle.rs` | 130 | migrate.py state detection | **Ported** |
| `tests/constraints.rs` | 406 | database.md integrity + Python repo tests | **Ported** |
| `tests/gui_inventory.rs` | 190 | image_reads.py GUI queries | **Ported** |
| `tests/doctor_basic.rs` | 60 | db_doctor maintenance command | **Ported** |
| `tests/retry_selection.rs` | 92 | retry-errors contract | **Ported** |

## src/lib.rs — Crate aggregate + public API surface

Python reference: Aggregate of submodules scattered across `forza/db/`, `forza/application/gui_read/`, `forza/application/gui_read_service.py`.

Status: **Ported**. Declares 8 modules; re-exports public API matching Python's `GuiReadService` + repository layer. Defines `test_support` module for demo seeding (mirrors Python's `forza/db/testing.py`). Defines `prelude` with `known_hashes` / `known_path_hashes`.

## src/connection.rs — Connection contract: WAL + busy_timeout + foreign_keys ON

Python reference: `forza/db/session.py` — `create_sqlite_engine()` + `_install_sqlite_pragmas()`. Python sets `PRAGMA foreign_keys = ON` via event listener; explicitly runs `PRAGMA journal_mode=WAL`.

Status: **Ported**. `configure_connection()` mirrors 3 mandatory pragmas: WAL, busy_timeout (5000ms — Rust-specific addition; Python uses `timeout: 30` in connect_args), foreign_keys ON. `connection_pool()` builds r2d2 pool with per-connection init applying all 3 pragmas.

## src/schema_ddl.rs — Exact DDL from audited Python baseline

Python reference: SQLModel entities (`forza/db/entities/*.py`) + Alembic migrations (`0001_db_vnext_baseline.py`). Rust DDL generated from real 0.21.0-beta.1 SQLite snapshot via `tools/generate_db_schema.py`.

Status: **Ported (DDL exact)**. Contains all 19 CREATE TABLE statements in dependency order, matching Python entity model exactly. All ~30 CREATE INDEX statements including partial unique indexes (`idx_attempts_one_accepted_per_result`, `idx_runtime_one_preflight_per_run`). All CHECK constraints, vocab checks, foreign keys, UNIQUE constraints preserved verbatim from audited baseline. SCHEMA_VERSION = 1 stamped into PRAGMA user_version.

## src/migration.rs — Clean-break: creates-from-zero via DDL + PRAGMA

Python reference: `forza/db/migrate.py` — Alembic-based migration layer with `detect_database_state()`, `upgrade_database()`.

Status: **Ported (conceptually, fundamentally different approach)**. Rust abandons Alembic entirely. Creates-from-zero with full DDL and stamps PRAGMA user_version. `SchemaStatus` enum mirrors Python's DatabaseSchemaState: Empty, Current, Incompatible (replaces UNMANAGED/OUTDATED/MISSING). `upgrade()` creates all tables in one transaction with FK deferred-off, then stamps version and re-enables FKs. Refuses to touch foreign-version databases. "Clean-break" policy preserved: Rust never opens Python-created databases in production.

## src/entities.rs — Intentionally omitted

Rust deliberately avoids SQLModel-style entity classes. All data represented as plain structs in repository/query modules with raw SQL queries. Deliberate architectural choice (no ORM dependency inversion). Python entities (`forza/db/entities/*.py`) replaced by Rust structs + raw SQL throughout crate.

## src/error.rs — Typed DbError enum via thiserror

Python reference: Python uses SQLAlchemy/rusqlite-native errors directly or wraps in RuntimeError. No dedicated DbError enum exists.

Status: **Ported (+)**. `DbError` enum with 3 variants: Sqlite(rusqlite::Error), Pool(String), SchemaState { message }. Implements std::fmt::Display, std::error::Error, From conversions for rusqlite::Error, std::io::Error, r2d2::Error.

## src/doctor.rs — Foundation only; Fase 8 adds run-counter/review checks

Python reference: `forza/application/db_doctor/` — DB Doctor maintenance command (`python -m forza maintenance db-doctor`).

Status: **Partially ported (foundation)**. `DoctorCheck` / `DoctorReport` structs mirror JSON output format of Python DB Doctor. `integrity_check()` runs PRAGMA integrity_check. `foreign_key_check()` runs PRAGMA foreign_key_check + collects violations. `run_basic_checks()` combines integrity + FK checks + schema status label. `doctor_on_path()` convenience wrapper: open + check in one call, handles empty databases gracefully.

**Not ported:** run-counter checks, review business key canonicality checks, open case flag matching — Fase 8 additions (noted in doc comment).

## src/gui_queries.rs — GUI inventory queries with processing status derivation

Python reference: `forza/application/gui_read/image_reads.py` — `GuiImageReadQueries.list_images()`, `_apply_processing_status_filter()`, `_latest_processing_statuses()`, `image_filter_values()`.

Status: **Ported**. `ImageInventoryRow` struct mirrors Python's `GuiImage` projection (id, current_name, file_status, best_lap_status, processing_status, file_size_bytes). Rust omits semantic_name, race_date, mime_type — deliberate inventory-surface simplification. PROCESSING_PROJECTION SQL uses same COALESCE/CASE logic as Python's `_processing_status_for_result()`: pending/running → processing, ok → processed_ok, cancelled → cancelled, else → processed_error. Skipped detection via latest non-process run_input identical. `image_inventory()` builds dynamic WHERE clauses from filter parameters; orders by LOWER(current_name), id (matching Python case-insensitive sort). Duplicate group filtering mirrors `_apply_duplicate_group_filter()`. `image_inventory_options()` returns distinct tracks and runs for GUI dropdowns, matching Python's `image_filter_values()`.

## src/image_detail.rs — Image detail queries with 5-tab projections

Python reference: `forza/application/gui_read/image_reads.py::get_image()` + `lap_reads.py` + `GuiReadService.get_image()`.

Status: **Ported**. `ImageDetailMeta` struct mirrors Python's `GuiImage` with all fields including processing_status derived via same COALESCE/CASE logic. `DetailLapRow` / `DetailResultRow` / `DetailAttemptRow` structs mirror Python lap/result/attempt projections for GUI detail tabs. `image_detail_meta()` loads one image with same processing status derivation as inventory. `laps_for_image()` queries lap_records by image_file_id ordered by lap_index (Python uses created_at.desc, lap_index asc — slight ordering difference). `results_for_image()` joins extraction_results with extraction_runs for backend/prompt_name, ordered by created_at DESC. `attempts_for_image()` queries extraction_attempts by image_file_id ordered by created_at DESC, attempt_number ASC (matches Python's `list_extraction_attempts` ordering).

## src/image_debug.rs — 1:1 port of all debug read functions

Python reference: `forza/application/gui_read/image_debug_reads.py` — entire file is direct port target.

Status: **Ported**. All projection structs: `ImageDebugCase`, `DebugExtraction`, `DebugAttempt`, `DebugLap`, `DebugReview`, `ImageDebugDetail` — match Python's equivalents exactly. `list_image_debug_cases()` mirrors `_cases_for_images()`: fetches images ordered by updated_at DESC, limited; batch-subqueries for processing statuses, results-by-image, lap/review/artifact counts. Python uses SQLAlchemy ORM queries; Rust uses raw SQL with window functions + IN-list batching. `get_image_debug_detail()` mirrors `_detail_for_image()`: loads image, all results, selected result's attempts, laps, reviews, raw evidence (raw_response/parsed_json from accepted attempt), timeline. `get_image_debug_detail_by_result()` resolves by extraction_result_id to owning image_file_id then delegates. `build_timeline()` mirrors `_timeline()`: same event construction + sorting logic. Rust omits artifact events + first_seen_at (minor difference).

## repositories/runs.rs — Full insert/update pipeline for runs, inputs, results, attempts

Python reference: `forza/db/repositories/runs.py`, `run_inputs.py`, run creation/extraction pipeline in Python's application layer.

Status: **Ported**. `RunInsert` struct with `demo()` helper. `RunMetadata` captures full LLM/image configuration (17 metadata columns). `RuntimeSnapshotInsert` captures preflight runtime state. `insert_prompt_snapshot()` with ON CONFLICT DO NOTHING for deterministic hash-based identity. `link_run_prompt_snapshot()`, `insert_runtime_snapshot()` — full evidence persistence. `insert_run()` creates extraction_runs row with seed defaults. `update_run_metadata()` replaces seed defaults with live config. `insert_input_and_result()` atomic run_input + extraction_result creation with RETURNING id pattern. `insert_processed_input()` real source path + process_reason ('full_run'/'force'/'retry_errors') vocabulary. `AttemptInsert` captures all 39 fields of extraction_attempts table. `insert_attempt_full()` inserts with full evidence payload. `finalize_result_ok()` updates result to 'ok' with accepted_attempt_id + token stats. Lifecycle transitions: `mark_run_running()`, `complete_run()`. Hash lookup: `find_image_id_by_hash()`. Guarded insert: `insert_accepted_attempt()` (only when result status is ok/error/cancelled).

## repositories/reviews.rs — Review candidate detection + upsert logic

Python reference: `laps.py::_append_row_review_candidates()`, `review_identity.py::case_business_key()`, `reviews.py::ReviewRepository.upsert_review_cases()`. Imports from `forza_domain::review_rules`.

Status: **Ported**. `LAP_SCOPED` / `IMAGE_SCOPED` constants mirror Python's equivalents. `canonical_business_key()` mirrors `_canonical_key()`: LAP-scoped uses {reason}:{image}:{lap_index}, IMAGE-scoped uses {reason}:{image}, fallback uses {reason}:fallback:{source}:{driver}:{best}. `query_review_candidates()` reads all lap_records + applies same review trigger rules: dirty+is_best_lap, weather_unknown, track_unknown/ambiguous/not_in_reference, class_unknown/invalid, driver_name triggers (numeric_prefix/invalid_symbol), car_empty/not_in_reference. Uses embedded reference data from forza_domain. `upsert_review_cases()` mirrors Python upsert logic: auto-resolves open cases whose condition disappeared, preserves user-owned terminal states (resolved/ignored), inserts new candidates with next case number. Returns (inserted, kept, auto_resolved) — same semantics as Python's (inserted, kept, removed).

**Not ported:** Rain-time suspicious check — Fase 8½ addition (same as Python's `_append_rain_time_review_candidates()` which exists but is deferred).

## repositories/images.rs — Partial: known_hashes + retry selection; upsert deferred

Python reference: `forza/db/repositories/images.py` — `ImageFileRepository.upsert()`, `by_hash()`.

Status: **Partially ported**. `known_path_hashes()` returns path->hash map for available files with extraction results (ok or error). `known_hashes()` returns distinct hashes of available images with extraction results. `list_failed_images_for_retry()` uses ROW_NUMBER window function to find latest-error images among available files — mirrors Python retry-errors selection contract. `ImageFileInsert` struct + `insert_image_file()` provide identity inserts with defaults for image_format='png', mime_type='image/png', file_status='available', best_lap_status='pending'.

**Not ported:** Full Python `upsert()` logic (existing-file lookup, path conflict resolution, metadata application, duplicate_of_image_file_id linking) — deferred to Fase 8.

## repositories/laps.rs — Partial: export + insert; add_result deferred

Python reference: `forza/db/repositories/laps.py` — `LapRepository.add_result()`, `export_flat()`.

Status: **Partially ported**. `ExportFlatRow` struct mirrors Python's `ExportLap` for CSV/PDF output artifacts (15 fields). Note: Rust omits is_best_lap + semantic_name fields that Python includes. `list_clean_flat()` queries best-lap rows joined with image metadata for export, orders by track/race_class/driver/best_lap_ms, computes "mine" flag from gamertag comparison — mirrors Python's `export_flat()`. `LapRecordInsert` struct + `insert_lap_record()` insert lap record with driver_normalized = LOWER(driver), car_normalized = LOWER(car), track_normalized = LOWER(track), temp_c computed from temp_f via SQL formula, created_at = datetime('now').

**Not ported:** Full Python `add_result()` (creates run_input + extraction_result + lap records in one call), `list_by_run()`, `for_image_file()`, complex review candidate detection logic — deferred to Fase 8.

## repositories/corrections.rs — Full manual correction path

Python reference: `forza/db/repositories/review_corrections.py`.

Status: **Ported**. `CORRECTION_FIELDS` constant mirrors Python's allowed fields: dirty, track, weather, race_class, car, driver. `apply_manual_correction()` finds review case by case_number, validates field vocabulary, updates linked lap record (dirty as boolean; track/car with reference data normalization), persists correction to review_corrections with stable_key identity (ON CONFLICT DO UPDATE for deterministic reapply), resolves review case as confirmed. Uses `forza_domain::reference_data` + `normalizer` for track/car name normalization — mirrors Python's reference data lookup.

## repositories/best_laps.rs — mark_best_laps + frontier integration

Python reference: `laps.py::mark_best_laps()`, `frontier.py::FrontierCalculator`, `_latest_rows_per_image()` helper.

Status: **Ported**. `LapExportRow` struct loads all lap_records ordered by track/race_class/driver/best_lap_ms. Implements `FrontierLap` trait for both `&LapExportRow` + `LapExportRow` (borrowed + owned), mirroring Python's entity-to-calculator interface. `latest_rows_per_image()` filters to only most recent run's lap rows per image (lexicographic max on timestamp-prefixed run_id) — mirrors Python's `_latest_rows_per_image()`. `mark_best_laps()` clears all is_best_lap flags, loads all rows, filters to latest-per-image candidates, computes winners via `clean_frontier_rows` (with gamertag) or `simple_best_rows` (without), sets is_best_lap=1 on winners, updates image_files.best_lap_status to contributing/non_contributing — mirrors Python's `mark_best_laps()` exactly.

## Tests

| Test file | Python Reference | Status | Tests |
|-----------|-----------------|--------|-------|
| `connection_contract.rs` | session.py pragma tests | **Ported** | 3: WAL, foreign_keys, busy_timeout + pool idempotence |
| `schema_lifecycle.rs` | migrate.py state detection | **Ported** | 5: empty→current, idempotence, all tables verified, version refusal |
| `constraints.rs` | database.md integrity + Python repo tests | **Ported** | 9: partial unique indexes ×2, FK policies (RESTRICT/CASCADE/SET NULL), vocab checks, uniqueness constraints |
| `gui_inventory.rs` | image_reads.py GUI queries | **Ported** | 7: filters, ordering, status derivation, options, file_status/best_lap_status |
| `doctor_basic.rs` | db_doctor maintenance command | **Ported** | 3: ok/empty/FK violation detection |
| `retry_selection.rs` | retry-errors contract | **Ported** | 3: latest-error selection logic (only-latest, older-ok vs newer-error, newer-ok shadows older) |

## Overall assessment

`forza-db` is **substantially fully ported** for its current scope. Core infrastructure (connection, schema DDL, migration, error handling) + all GUI read queries (inventory, detail, debug) are complete. Repository insert paths for runs, attempts, corrections, best-laps frontier computation fully implemented. Review candidate detection + upsert logic ported with embedded reference data integration.

**Deferred to Fase 8/Fase 8½:**
1. Full image file `upsert()` logic (path conflict resolution, metadata application) — `repositories/images.rs`
2. Complex lap record creation pipeline (`add_result`) with run_input/result/lap batch insertion — `repositories/laps.rs`
3. Rain-time suspicious review check — `repositories/reviews.rs`
4. DB Doctor run-counter + review business key canonicality checks — `doctor.rs`

Crate follows clean-break policy documented in `docs/contracts/database.md`: Rust creates own databases from zero via DDL, never opens Python-created databases in production, uses raw SQL (rusqlite) instead of ORM layer.
