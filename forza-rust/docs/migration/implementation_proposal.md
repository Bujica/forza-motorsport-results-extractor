# Proposal: Completing the Python → Rust Migration

**Date:** 2026-08-27
**Current status:** ~55% functional coverage across all crates (Phase 1 complete)
**Target:** 100% functional equivalence with Python v0.21.0-beta.1

---

## Phase Completion Log

| Phase | Status | Date completed | New lines added | Tests added |
|-------|--------|---------------|-----------------|-------------|
| **Phase 1: Database Completeness** | ✅ Complete | 2026-08-27 | ~679 lines across 4 files | — (existing tests pass) |
| **Phase 2: Application Layer Completeness** | ✅ Complete | 2026-08-28 | ~350 lines across 4 files | — (existing 86 tests pass) |
| **Phase 3: CLI Completeness** | ✅ Complete | 2026-08-28 | ~100 lines across 2 files + full doctor battery (~1,100 lines, 2026-08-29) | 5 new doctor tests (101 total) |
| **Phase 4: PDF Visual Renderer** | ✅ Complete | 2026-08-29 | ~700 lines rewritten in `pdf.rs` | 5 new renderer tests (139 total) |
| **Phase 5: Performance Dashboard** | ⏭️ Skipped by decision | — | Python implementation will be redone upstream | — |
| **Phase 6: Pipeline Completeness** | ✅ Complete | 2026-08-29 | ~120 lines across 5 files | 2 new pipeline tests (141 total) |
| **Phase 7: LM Studio Completeness** | ✅ Complete | 2026-08-29 | ~200 lines across 6 files | 2 new evidence tests (143 total) |

---

## Current State Summary

| Crate | Ported | Partially ported | Not started | Total .rs files |
|-------|--------|-----------------|-------------|-----------------|
| forza-domain | 13 | — | — | 13 |
| forza-config | 4 | 1 | — | 5 |
| forza-db | 12 | 5 | — | 17 |
| forza-pipeline | 6 | 2 | — | 9 |
| forza-lmstudio | 5 | 4 | 1 (example) | 10 |
| forza-output | 2 | 1 | — | 4 |
| forza-app | 6 | 7 | 3 | 13 |
| forza-cli | 1 | — | — | 1 |
| forza-gui | 5 | — | — | 6 (incl. slint) |

**Tests:** 147 passing across all crates (Phase 5 skipped by decision). Gates: `cargo fmt`, `cargo clippy -- -D warnings`, `cargo test` — all green.

### Audit Remediation (2026-08-29) ✅ Complete

Parity audit of Phases 1–3 against the Python source found and fixed:
1. **corrections.rs crash** — weather/race_class updates referenced non-existent `weather_normalized`/`race_class_normalized` columns; now mirrors `_apply_to_lap` (image-scoped fields apply to every lap of the image, lap-scoped require lap_index, un-dirtying strips the dirty symbol, `_bool_value` truthy-set semantics, casefold via to_lowercase).
2. **doctor review identity NULLs** — canonical key recomputation now renders NULL lap_index as an empty segment and re-normalizes `driver_normalized or driver`, matching `review_identity.py` (no more false positives on `review_business_key_not_canonical`).
3. **reconcile_abandoned_runs** — heals process inputs without results (creates cancelled results with `error_type='cancelled'`, message `abandoned_run_recovered`), recomputes all run counters from relational rows, finalizes the run as `failed` (Python semantics).
4. **runner path conflict** — `upsert_image_for_run` retires the previous available owner of a `current_path` before inserting a new hash (prevents `available_image_path_conflicts` doctor errors).
5. **upsert_image_file parity** — existing-row match now requires hash equality; UPDATE/INSERT apply file_modified_at/race_datetime/race_date/race_datetime_source/image_metadata_json; missing_at is set/cleared with file_status.
6. **add_result** — Unicode normalization (to_lowercase vs SQLite LOWER), `strip_dirty_symbol` instead of `trim('*')`, collision-free ids (`lap-{result}-{index}`), domain `fahrenheit_to_celsius` for temp_c.
7. **rain-time candidates** — bucket-minima comparison (best rain vs best dry per track/class) flags every rain row of the bucket, like Python.

4 new regression tests cover fixes 2, 3 and 7 plus the weather-correction crash.

---

## Implementation Plan — 7 Phases

Each phase is designed to be executed by a single agent within the 130K context window. Phases are ordered by dependency (earlier phases must complete before later ones can compile).

### Phase 1: Database Completeness (`forza-db`)

**Dependencies:** None (schema already exists)
**Estimated scope:** ~600 lines of new Rust code across 4 files + 3 test files

#### 1.1 Full image upsert in `repositories/images.rs`

Port Python's `ImageFileRepository.upsert()` from `forza/db/repositories/images.py:21-99`.

New functionality needed:
- **Path conflict resolution:** When a new hash arrives at an existing path, mark the previous owner `"missing"` with `missing_at = now`
  ```sql
  UPDATE image_files SET file_status='missing', missing_at=?
  WHERE current_path=? AND file_hash!=? AND file_status='available'
  ```
- **Metadata application:** `_apply_metadata()` sets size_bytes, image_format, mime_type, width_px, height_px, bit_depth, color_mode, file_modified_at, race_datetime, race_date, race_datetime_source from ImageMetadata struct. Also copies `image_metadata_json` (stripping duplicate_of_image_file_id and file_modified_at keys).
- **Filesystem existence check on update:** If current_path no longer exists on disk → mark `"missing"`.

**Rust implementation approach:** Add methods to existing `ImageFileRepository`:
- `fn upsert(&self, conn: &Connection, params: UpsertParams) -> Result<ImageFileEntity, DbError>`
- `fn resolve_path_conflict(&self, conn: &Connection, path: &str, hash: &str)` — marks previous owners missing
- `fn apply_metadata(&self, entity: &mut ImageFileEntity, metadata: &ImageMetadataInfo)`

**Test file:** `tests/image_upsert.rs` — 5 tests covering new entity creation, existing update with conflict resolution, metadata application, filesystem disappearance detection.

#### 1.2 Lap repository additions in `repositories/laps.rs`

Port three functions from `forza/db/repositories/laps.py`:
- **`add_result()`** (lines 172-244): Creates ExtractionResultEntity if missing, then iterates session entries creating LapRecordEntity rows with idempotency guard (`(extraction_result_id, lap_index)` uniqueness)
- **`list_by_run()`** (line 246-253): Single query `SELECT * FROM lap_records WHERE run_id=? ORDER BY image_file_id, lap_index`
- **`for_image_file()`** (lines 255-262): Single query `SELECT * FROM lap_records WHERE image_file_id=? ORDER BY created_at DESC, lap_index`

Also port `_append_rain_time_review_candidates()` from lines 116-134: Collects best-lap rows, builds dict of `(track, race_class, weather) → best_lap_ms`, for each rain lap compares against dry lap on same `(track, race_class)` — if `best_rain < best_dry` appends `"weather"` review case with trigger `"rain_time_suspicious"`.

**Rust implementation approach:** Add methods to existing `LapRepository`:
- `fn add_result(&self, conn: &Connection, result: ExtractionResultEntity, run_id: &str, image_file_id: &str) -> Result<Vec<LapRecordEntity>, DbError>`
- `fn list_by_run(&self, conn: &Connection, run_id: &str) -> Result<Vec<LapRecordEntity>, DbError>`
- `fn for_image_file(&self, conn: &Connection, image_file_id: &str) -> Result<Vec<LapRecordEntity>, DbError>`
- `fn append_rain_time_review_candidates(&self, conn: &Connection, candidates: &mut Vec<ReviewCase>)` — pure logic helper

**Test file:** `tests/lap_repository.rs` — 4 tests covering add_result idempotency, list_by_run ordering, for_image_file ordering, rain-time suspicious detection.

#### 1.3 DB Doctor full check battery

Port from `forza/application/db_doctor/`:
- **Run counter checks** (`run_checks.py:9-57`): `runs_left_running` (SELECT COUNT WHERE status='running'), `run_counters_mismatch` (8-column multi-subquery comparing all counters against actual row counts)
- **Review business key checks** (`review_checks.py:85-152`): `review_business_key_uses_lap_record_id` (count keys containing volatile lap_record_id), `review_business_key_not_canonical` (count rows where business_key != entity_identity canonical_key)

Also port additional checks from run_checks.py and review_checks.py for completeness.

**Rust implementation approach:** Extend existing `doctor.rs` module:
- Add new check functions returning `Vec<DbDoctorCheck>` with severity levels (error/warning/info)
- Port the canonical key computation from `forza/db/review_identity.py` into a Rust function in `forza-db`

**Test file:** `tests/doctor_full.rs` — 3 tests covering run counter mismatch detection, review business key validation, full doctor report on seeded database.

---

### Phase 2: Application Layer Completeness (`forza-app`) ✅ Complete

**Dependencies:** Phase 1 (lap repository additions)
**Completed:** 2026-08-28
**Scope:** ~350 lines across 4 files — all gates green, 86 tests passing

#### 2.1 Multi-worker parallel extraction in `extraction_runner.rs` ✅ Done

Port Python's `_process_parallel()` from `forza/application/run_service.py`. The current Rust runner processes images sequentially on a single thread.

New functionality:
- Configurable worker count (`cfg.image.workers`) spawning multiple Tokio tasks
- Each worker runs the full extraction loop (encode → LM Studio call → parse/validate → persist)
- Shared `RunControl` for cooperative cancel/pause across all workers
- Event aggregation from multiple workers into a single channel

**Rust implementation approach:** ✅ Implemented. `RunParams` gained `workers: u32` field sourced from `cfg.workers`. When `workers > 1`, images are split round-robin into batches, each worker thread spawns its own single-threaded tokio runtime + SQLite connection + LMStudioBackend, events merge via mpsc channel. Sequential mode (`workers == 1`) preserves the original loop. Workers metadata recorded in `RunMetadata`.

#### 2.2 Abandoned run reconciliation ✅ Done

Port Python's `reconcile_abandoned_runs()` from `forza/application/run_service.py`.

**Rust implementation:** ✅ Added `reconcile_abandoned_runs(&Connection) -> Result<usize, DbError>` to `forza-db::repositories::runs`. Queries all `extraction_runs` with `status='running'`, per-run: updates pending/running results to `cancelled`, sets `operational_error_code='abandoned'` on the run row. Per-run try/except so one corrupt run doesn't block others. Called at the start of `run_async()` before discovery phase.

#### 2.3 Correction application ✅ Done

Port Python's `rebuild_derived_state()` from `forza/application/rebuild_service.py`.

**Rust implementation:** ✅ Added `apply_all(&Connection) -> Result<usize, DbError>` to `forza-db::repositories::corrections`. Joins `review_corrections` with `review_cases` to get `lap_record_id`, applies each correction (dirty flag, track/weather/race_class/car/driver normalization), returns count applied. `rebuild()` in `forza-app` now calls `apply_all()` before `mark_best_laps()`. `RebuildOutcome` gained `corrections_applied` field.

---

### Phase 3: CLI Completeness (`forza-cli`) ✅ Complete

**Dependencies:** Phase 1 (DB Doctor full checks), Phase 2 (abandoned run reconciliation)
**Completed:** 2026-08-28
**Scope:** ~100 lines across `src/main.rs` + `Cargo.toml` — all gates green, 96 tests passing
**Follow-up (2026-08-29):** full DB doctor battery ported — `forza-db/src/doctor.rs` now runs all 63 checks from the Python modules (status vocabulary, run/input contract, image file filesystem checks, best-lap state, review/flag parent chains, artifact evidence incl. `request_hash`/prompt-snapshot recomputation, and schema drift against the shipped DDL baseline). `DoctorCheck` gained a real `count` field; `ok` semantics match Python (only error-severity checks fail the report). First real-DB run flagged 12 results missing `request_hash`/`runtime_snapshot_id`/`prompt_snapshot_id` — resolved in Phase 7 (evidence chain stamping); existing rows heal after a fresh run (`db-reset` + rerun).

#### 3.1 Add --debug flag ✅ Done

Added top-level `--debug` argument to `Cli` struct. Pass it through to `forza_config::load_config()` (which uses it for tracing subscriber initialization) and all subcommands that load config.

#### 3.2 Full db-status command ✅ Done

Replaced the simplified schema-only status with full table row counts for all 13 relational tables: `image_files`, `extraction_runs`, `extraction_results`, `extraction_attempts`, `lap_records`, `review_cases`, `review_corrections`, `image_flags`, `export_artifacts`, `reference_tracks`, `reference_cars`, `external_record_imports`, `external_lap_records`. Uses `table_count()` helper with fallback to 0 for tables that may not exist.

#### 3.3 Full db-doctor command ✅ Done

Replaced the simplified doctor with full check battery via `run_full_doctor()` including multi-severity grading (error/warning/info). Handles empty/missing DB gracefully (delegates to `doctor_on_path()` which skips table queries). Output JSON when `--json` flag is set, text format otherwise. Exit code 2 if not all checks pass (matching Python's `SystemExit(2)`).

#### 3.4 Exclusive-lock safety on db-reset ✅ Done

Added `ensure_exclusive_access()` that opens a new SQLite connection and attempts `BEGIN EXCLUSIVE` + `COMMIT`. If the database is locked by another connection → exits with explanatory message. If the file is not a valid SQLite database → passes (legitimate for db-reset). Added WAL/SHM sidecar warnings before deletion.

#### 3.5 Reference data loading

Reference data loading is already available through `forza_db::repositories::reference_*` modules. The rebuild command passes `gamertag` to `rebuild()` which handles reference matching internally.

#### 3.6 Export artifact recording

Export artifact recording is deferred to a later phase. The current export writes CSV/PDF without artifact persistence.

---

### Phase 4: PDF Visual Renderer (`forza-output`) ✅ Complete

**Dependencies:** None (content plan already ported)
**Completed:** 2026-08-29
**Scope:** ~700 lines rewritten in `src/pdf.rs` + `tests/pdf_render.rs` — all gates green, 139 tests passing

**Implementation notes:** Dependency-free PDF writer (no genpdf): A4 layout with embedded Helvetica/Helvetica-Bold AFM width tables for centering/wrapping, WinAnsiEncoding text (accents + dagger symbol), named `/toc` destination with link annotations on every page, two-phase pagination (TOC pages counted before sections so heading page numbers are exact), ReportLab-matched styles (cover, track-heading bars, class-coloured table headers, player/external/alternating row fills, red dirty-lap highlighting per `cfg.pdf`), timestamped `archive/` archiving, and `used_files` returned like Python's `generate_pdf`. `build_pdf_plan_ext` adds external records + render options; `build_pdf_plan` kept as compat wrapper for the golden test. Validated visually against real data (13-page report).

#### 4.1 Replace lightweight renderer with full ReportLab-equivalent

The current `render_pdf()` produces a valid but minimal text-based PDF. Port the full ReportLab rendering from `forza/output/pdf.py`.

New functionality needed:
- **Cover page:** "Forza Motorsport" title, "Best Laps" subtitle, horizontal rule, gamertag name, date in Portuguese format ("27 de Agosto de 2026"), stats summary, optional external record legend
- **TOC page:** TableOfContents with levelStyles, "Track Index" heading
- **Track sections:** TrackHeading paragraph (dark background, white text), then for each class → styled table
- **Row coloring:** ROW_PLAYER="#FFF8DC" (warm yellow), ROW_EXTERNAL="#D6EAF8" (light blue), ROW_ALT="#F8F9FA" (alternating grey)
- **Dirty-lap red highlighting:** `<font color="#E74C3C">time {symbol}</font>` when cfg.pdf.show_dirty_lap_symbol and row.dirty
- **Footer callback:** centred page number, right-aligned "TOC" with clickable link rect to bookmark
- **Archiving:** Move existing PDF to `archive/` subfolder with timestamped filename

**Rust implementation approach:** Use the `pdf` crate (https://crates.io/crates/pdf) or `genpdf` for styled table rendering. The content plan (`build_pdf_plan`) already produces the exact data structure needed — just replace the lightweight renderer with full layout rendering.

**Test file:** `tests/pdf_render.rs` — 2 tests verifying PDF structure (cover page, TOC, track sections present) and archived file creation.

---

### Phase 5: Performance Dashboard (`forza-gui`)

**Dependencies:** Phase 1 (lap repository additions for external records), Phase 4 (PDF renderer complete)
**Estimated scope:** ~500 lines across lib.rs + worker.rs + new performance module

#### 5.1 Performance data service in `forza-app`

Port Python's `performance_service.py` from `forza/application/performance_service.py`. This is a pure analytics module (no Qt, no DB, no filesystem).

New types/functions:
- `PerformanceSummary` — 5 summary cards (sessions count, records held, closest community gap, most improved track, top rival driver)
- `PerformanceDashboard` — 7 sections: cards, records (up to 12 rows), strengths (up to 8), improvement_targets (up to 8), car_usage (up to 10), car_strength (up to 10), recent_best (up to 8)
- `CarPerformance` — per-car analytics with dominance_score calculation
- `compute_performance_summary()`, `build_dashboard()`, `build_car_performance()`

**Rust implementation approach:** New module `src/services/performance.rs` in forza-app. Pure logic functions matching Python signatures. Uses existing lap record and external record types from forza-db.

#### 5.2 Performance worker + GUI integration

Port Python's performance_worker.py and performance_controller.py into the Slint architecture:
- Worker thread request/response for `LoadPerformance`
- Response handler in lib.rs populating table models
- UI page callback on "Performance" sidebar item (currently shows placeholder text)

**Rust implementation approach:** Add to worker.rs Request/Response variants. Add page callback in lib.rs. Replace Performance page placeholder with actual data tables using VecModel instances.

---

### Phase 6: Pipeline Completeness (`forza-pipeline`) ✅ Complete

**Dependencies:** None
**Completed:** 2026-08-29
**Scope:** ~120 lines across 5 files — all gates green, 141 tests passing

**Implementation:** `ImageMetadataInfo` gained `file_modified_at`/`race_datetime` (UTC RFC3339, mtime is the official race-date source like Python), `race_date`, `race_datetime_source`, and `image_metadata_json` (buffer-layout facts via serde_json — PIL-style info is unavailable under the `image` crate). Both DB write paths (extraction runner image registration + inventory sync UPDATE/INSERT) persist the new columns. `log_duplicate_skips()` ported to `planning.rs` with `tracing` and called after run planning, mirroring Python's inventory register step.

#### 6.1 Timestamp fields in metadata.rs

Add `file_modified_at`, `race_datetime`, `race_date`, `race_datetime_source` fields to `ImageMetadataInfo`. Capture via `fs::metadata()` at inspection time. Also add `image_metadata_json` (raw image info dict) — use `image` crate's buffer layout info as fallback when PIL-style metadata is unavailable.

#### 6.2 Log duplicate skips

Add `log_duplicate_skips()` function matching Python's logging helper for duplicate skip events during planning. Uses Rust tracing subscriber.

---

### Phase 7: LM Studio Completeness (`forza-lmstudio`) ✅ Complete

**Dependencies:** None (all core functionality already ported)
**Completed:** 2026-08-29
**Scope:** ~200 lines across 6 files — all gates green, 143 tests passing

**Implementation:** Evidence chain completed (this is what the DB doctor flagged on real data): `forza-db/src/evidence.rs` now owns `canonical_request_hash` (Python-golden tested, `json.dumps`-compatible canonicalisation incl. ensure_ascii and sorted keys); `AttemptInsert` gained `runtime_snapshot_id` persisted by `insert_attempt_full`; the extraction runner stamps every attempt with the preflight runtime snapshot id and a recomputed request hash over exactly the persisted columns, and every result row retains the run's prompt snapshot id. Integration test `full_doctor_accepts_stamped_evidence_chain` proves a stamped run passes the full doctor battery (all previously-ERRORing checks at 0). The backend's own legacy null-field request hash is overridden by the runner's canonical one. `on_attempt` callback parity already existed; mid-run reload `attempt_recheck` snapshots remain a refinement (backend does not expose reload events).

#### 7.1 Persistence hooks

Port Python's `_on_attempt` and `_on_runtime_snapshot` callbacks from `backend.py`. Add optional callback parameters to `extract()` method for attempt recording and runtime snapshot persistence.

#### 7.2 Rich metadata structs (optional)

Reintroduce flattened image metadata fields (`request_image_format`, `request_image_mime_type`, etc.) into `ModelAttemptRecord` if downstream consumers need them. Currently these are dropped in favor of the simplified flat struct.

---

## Execution Order & Agent Strategy

Each phase should be executed by a single agent to stay within 130K context window:

| Phase | Agent task | Context usage |
|-------|-----------|---------------|
| **Phase 1** | Complete forza-db (upsert, laps, doctor) | ~45K — focused on one crate + schema |
| **Phase 2** | Complete forza-app (parallel workers, reconciliation, corrections) | ~35K — depends on Phase 1 types |
| **Phase 3** | Complete forza-cli (--debug, full diagnostics, safety checks) | ~20K — small file modifications |
| **Phase 4** | Implement PDF visual renderer | ~30K — new rendering crate dependency + pdf.rs rewrite |
| **Phase 5** | Build performance dashboard (service + GUI integration) | ~40K — spans forza-app + forza-gui |
| **Phase 6** | Pipeline completeness (metadata timestamps, log skips) | ~10K — small additions to existing files |
| **Phase 7** | LM Studio completeness (persistence hooks, metadata fields) | ~15K — optional enhancements |

Total estimated new code: ~1,800 lines across 12+ new/modified files.

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| PDF crate API mismatch (genpdf vs ReportLab) | Medium | Spike test first — verify genpdf can produce styled tables + TOC before full implementation |
| Multi-worker concurrency bugs | Low | Tokio's join! is well-tested; bounded semaphore prevents resource exhaustion |
| Database constraint conflicts during upsert | Low | Clean-break policy means Rust DB starts empty; constraints only tested against seeded data |
| Performance dashboard query performance | Medium | Large lap datasets may need pagination; add limit/offset to GUI queries if needed |

---

## Success Criteria (per phase)

Each phase must pass:
1. `cargo check --all` — no compilation errors
2. `cargo fmt --all` — formatting compliance
3. `cargo clippy -- -D warnings` — lint compliance
4. `cargo test --all` — all existing tests still pass + new tests for new functionality

---

## Recommended Starting Point

**Phase 1 (Database Completeness)** is the recommended starting point because:
- It has no dependencies on other phases
- It unlocks Phase 2 (application layer needs lap repository additions)
- The DB Doctor full checks are needed by Phase 3 (CLI completeness)
- All SQL queries and Python source code are well-documented in the migration reports
