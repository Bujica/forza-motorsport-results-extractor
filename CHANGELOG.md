# Changelog

## 0.20.0-beta.1 - Public beta baseline

- Renamed the public product to **Forza Motorsport Results Extractor**.
- Clarified the supported target: **Forza Motorsport, 2023 release** results-screen screenshots.
- Added public app identity, repository/issue links, About dialog information, and build metadata.
- Added Windows portable beta bundle support with explicit runtime/development file separation.
- Kept processing local-first: screenshots are processed through the user-configured local LM Studio endpoint.

All notable changes to Forza Motorsport Results Extractor are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

No unreleased changes.

---

## [0.20.0] - 2026-06-18

GUI diagnostics and image workflow polish release.

### Added

- Added `Race Date` to the Images inventory using race metadata rather than file modification time.
- Added previous/next navigation to Image Details while keeping the debug bridge decoupled from image browsing.
- Added an image-centric `Diagnostics > Image Debug` surface with Overview, Image Metadata, Extraction Results, Attempts, Model Response, Parsed Data, Laps & Reviews, Artifacts, Runtime, and Timeline tabs.

### Changed

- Renamed the GUI `Developer Tools` section to `Diagnostics` and kept LM Studio runtime Overview, Image Debug, DB Doctor, and Logs under that section.
- Replaced the legacy result-centric Model Debug read/controller/model/view stack with the new Image Debug system; the old surface no longer remains in parallel.
- Moved `Records` directly below `Best Laps` in the main navigation and kept `Diagnostics` with lower utility sections.
- Renamed the Process full-folder action to `Run All` and made final run status include total elapsed time.
- Refactored Review candidate detection into explicit helper seams and added conservative SQL prefiltering so Review no longer materializes every lap row for most checks.
- Stabilized Review candidate row ordering after SQL prefiltering so lap-scoped Review cases keep deterministic image/lap ordering.
- Deduplicated GUI result-context read helpers shared by extraction-result and Image Debug read paths.
- Deduplicated LM Studio preflight runtime snapshot capture while preserving success and failure snapshot behavior.

### Fixed

- Fixed Image Debug review-case mapping so resolved Review evidence reads fields available on `ReviewCaseEntity`.
- Fixed invalid persisted race-class values in Review candidates by preserving the original model value while using `Unknown` as the validated Review envelope race class.
- Made extraction-attempt append fail before persistence when the parent extraction result is missing.
- Replaced a rebuild Review event string literal with `EventType.REVIEW_CASES_CREATED`.
- Removed dead local state from GUI lap dirty-write handling.

### Removed

- Removed the legacy `Model Debug` controller, table model, view, GUI read path, and static tests after replacing them with image-centric diagnostics.

### Validation

- Passed `python -m compileall -q forza`.
- Passed focused GUI/Image Debug, GUI read, raw-evidence, docs, Review, Run Service, rebuild, and DB repository suites during the release series.
- Passed `pytest` with 801 tests.
- Passed `python -m forza maintenance db-doctor --json` with `schema_state=current` and `ok=true`.
- Smoke-launched `python -m forza gui` after the Image Debug review mapping fix.

---

## [0.19.2] - 2026-06-18

Post-audit stabilization release.

### Changed

- Updated Records rivals to use the active Records filters and changed the operator-facing label from `Global rivals` to `Rivals`.
- Added relative gap percentages beside rival and Community Records gaps so opportunity ranking is based on proportional gap, not only absolute seconds.
- Marked new Community Records imports as the active snapshot, persisted imported external records as dry-weather records, and separated rejected rows from warnings in import metrics.
- Limited dirty-lap Review cases to dirty laps that affect Best Laps output, reducing non-actionable review noise.
- Optimized DB Doctor evidence checks with SQL/set-based raw evidence counting, batched artifact SQL-evidence lookup, file-size short-circuiting before hash checks, and streaming artifact hashing.

### Fixed

- Fixed persisted encoded-image payload metadata so request byte counts use the source image byte count rather than base64 length.
- Hardened Images rename rollback by validating filesystem postconditions before SQL updates and verifying rollback cleanup after failures.

### Validation

- Passed `python -m compileall -q forza`.
- Passed `pytest` with 790 tests.
- Passed `python -m forza maintenance db-doctor --json` with `schema_state=current` and `ok=true`.
- Smoke-launched `python -m forza gui`.

---

## [0.19.1] - 2026-06-17

### Changed

- Hardened DB Doctor schema drift checks so column validation covers reference-data tables and quotes SQLite identifiers.
- Limited Images input-folder missing-file reconciliation to available rows with a current path so background scans avoid walking irrelevant inventory records.
- Isolated abandoned-run reconciliation so one corrupt running run does not stop recovery of other abandoned runs.
- Made the shared database session provider initialize and close its SQLite engine under a lock so GUI workers cannot race lazy engine creation.
- Optimized Images processing-status projection so the GUI reads only the latest extraction result per image instead of loading full result history.
- Moved Images input-folder synchronization to a background worker so GUI startup is not blocked by filesystem hashing and metadata inspection.

---

## [0.19.0] - 2026-06-17

Performance Records release.

### Added

- Added a player-centric Records/Performance surface with track/class/weather records, community-record coverage, car usage, dominant-car analysis, progress history, and global rivals.
- Added a background Performance worker and pure application analytics service so Records refreshes do not block the GUI thread or bypass the GUI read facade.
- Added static guards for the simplified Process and Best Laps GUI surfaces.

### Changed

- Clarified that Records community comparisons use Best Laps external/community records and are comparable only for dry non-TCR combinations.
- Reworked Records into a filtered TrackRecord table with selected-combo detail instead of the previous dashboard-style summaries.
- Kept PDF generation and external spreadsheet import in Best Laps as the output workflow owner.
- Updated Best Laps to show the table and top summary/action surface without duplicating the same information in a lower text panel.

### Removed

- Removed the redundant Process Outputs card and its PDF/Rebuild controls from the Process screen.
- Removed the redundant lower Best Laps text detail panel.

---

## [0.18.0] - 2026-06-16

Images-first workflow release.

### Added

- Added Images-first inventory behavior so supported files in the input folder appear before model processing and can be selected for targeted runs.
- Added selected-image processing through the GUI Process worker boundary using stable `image_file_id` values.
- Added explicit Images actions for filesystem-backed rescan, semantic rename, export, and safe Delete.
- Added derived processing status for Images, including skipped inputs that were considered by a run without producing extraction results.
- Added duplicate-group inventory filtering that shows canonical and duplicate image rows together.

### Changed

- Promoted Images to the primary GUI workflow entry point and kept Process as run/progress control.
- Reworked image identity around current physical file path/name plus `file_hash`; semantic names remain presentation metadata.
- Updated Best Laps, Review, Debug, and GUI read paths to use current image identity instead of stale original filenames.
- Updated Images Run filtering to use `run_inputs.image_file_id`, including duplicate groups after base image filters.
- Simplified Best Laps participation state by removing the unsupported `excluded` status.
- Aligned Review and image-flag vocabularies around canonical reasons, including `driver_name`.
- Scoped `image_flags` to SQL infrastructure for duplicate lifecycle, Review lifecycle, and DB Doctor integrity checks; raw flags are no longer a normal GUI read/write surface.

### Removed

- Removed unsupported hidden/deleted/disposable image-file workflow residue from normal product behavior.
- Removed obsolete Process-first and dead image-controller actions that no longer had supported GUI workflows.
- Removed raw internal flags from normal Image Details and removed manual raw image flag GUI read/write facades.
- Removed unused SQL debug/attempt-summary views from the clean baseline.
- Removed obsolete Best Lap service plumbing superseded by the recompute service.

### Fixed

- Fixed renamed files still showing stale source names in Best Laps by relying on current image file identity.
- Fixed duplicate/skipped image rows appearing as unprocessed after a run had already considered them.
- Fixed GUI Delete and scan reconciliation so duplicate groups promote or resolve correctly when canonical or missing rows change.
- Fixed Images duplicate-group filtering so run/filter combinations expand to the full duplicate group after base filters.
- Fixed GUI-created/upgraded databases and DB Doctor checks to align with the clean Images-first schema contract.

### Validation

- Passed `python -m compileall -q forza`.
- Passed `pytest` with 748 tests.
- Passed `python -m forza maintenance db-doctor --json` with `schema_state=current` and `ok=true`.

---

## [0.17.1] - 2026-06-14

Best Laps DB/read-path patch.

### Changed

- Removed the unused `v_best_laps` SQLite view from the clean baseline and DB Doctor frozen-schema expectations.
- Added Best Laps-focused SQLite indexes for internal best-lap rows and active external records.
- Aligned the GUI best-lap read ordering with the new internal index while keeping tracks alphabetically ordered.
- Reduced repeated Best Laps table resize work without replacing content-based column sizing.

### Fixed

- Fixed GUI-created/upgraded databases so initial SQL reference tracks and cars are seeded, matching `maintenance db-upgrade`.
- Restored external spreadsheet import after DB reset/recreation by ensuring the SQL reference catalog exists before import.

### Validation

- Passed `python -m compileall -q forza`.
- Passed `python -m pytest -q`.
- Passed `python -m forza maintenance db-doctor --json` with `ok=true`.
- Reproduced `data/external/DataFM.xlsx` import after seeding references: 25,473 rows read, 511 active external records, 0 unmapped tracks, and 0 invalid laps.

---

## [0.17.0] - 2026-06-14

SQL/GUI clean-break release.

### Removed

- Removed experimental Lab/workbench/prompt-bench/sample-builder/Ground Truth runtime surfaces from the product package.
- Removed non-essential CLI aliases and legacy repair/maintenance commands that only preserved pre-cut compatibility.
- Removed runtime JSON authority for raw responses, external records, reference data, and generated artifact retention state.
- Removed obsolete raw-response artifact settings, raw artifact writer exports, and legacy raw response record tests.
- Removed Review duplicate-repair and DB Maintenance fixer surfaces after Review identity settled on canonical SQL identity.

### Changed

- Promoted SQL to the runtime authority for extraction runs, attempts, raw model evidence, reviews, image flags, best laps, community records, and reference catalog data.
- Kept GUI as the primary product surface and reduced the CLI to essential operational commands.
- Rebased reference track/car and Community Records behavior on SQL-backed runtime state with explicit seed/import boundaries.
- Split oversized active architecture/developer documentation into indexed shards and archived removed Lab architecture.
- Split oversized repository, DB Doctor, Run Service, and GUI write tests by product area while preserving behavior coverage.
- Consolidated removed-surface static guards and cleaned residual audit findings after the clean-break removals.

### Fixed

- Fixed limited runs so processable or retry-eligible images consume the selection limit rather than existing inputs.
- Updated DB Doctor artifact checks for SQL-first raw evidence and current-schema integrity.
- Removed stale documentation and Settings entries for raw response artifact directories and removed maintenance surfaces.

### Validation

- Passed `python -m compileall -q forza`.
- Passed `python -m pytest -q` with 733 tests.
- Passed focused split suites for DB repositories, DB Doctor, Run Service, and GUI write tests.
- Passed `python -m forza maintenance db-doctor --json` with `ok=true`.
- Passed `python scripts\c8_2_audit_docs_tests.py` with no hard-threshold docs/tests, no broken markdown links, and no test residue summary.

---

## [0.16.0] - 2026-06-12

Clean Break v4 quality release.

### Added

- Added the clean-break quality release plan and testing-policy implementation plan as archived release evidence.
- Added a permanent developer testing policy with pytest marker taxonomy, test-selection guidance, and release-gate expectations.
- Added DB Doctor hardening checks for final Ground Truth expected payloads, positive best-lap milliseconds, retention deadlines, raw evidence, artifact integrity, and related runtime/database consistency contracts.
- Added retention preview/apply service paths with safe candidate revalidation, auditable prune summaries, and CLI outcome counts.
- Added release-audit and contract-audit tooling for database, GUI, retention, schema, and release-readiness checks.

### Changed

- Normalized DB vNext release contracts, regenerated the active baseline schema, and kept SQLite as the runtime source of truth for model evidence, review, flags, best laps, Lab state, and maintenance checks.
- Moved GUI database read/write facades into `forza/application` and kept GUI controllers on application-level service boundaries.
- Normalized run-mode persistence so `--force` and `--retry-errors` stay out of `extraction_runs.mode`; selection flags are stored in run config.
- Tightened prompt naming, best-lap millisecond typing, review identity parsing, raw-evidence policy, event/backend constants, and LapRepository helper contracts.
- Reconsidered coverage omissions and restored backend/PDF modules to coverage accounting while keeping GUI omitted from the measured package coverage gate.
- Updated Best Laps, Review, DB Maintenance, Model Debug, Lab, retention, and release-gate documentation to match current behavior.

### Fixed

- Fixed LM Studio backend prompt binding so backend construction calls `get_system_prompt(prompt_id)` with the supported signature.
- Fixed Best Laps stale-cache refresh after hidden run/review events by reloading DB-backed rows when the stale section is entered.
- Fixed Review Queue resolved/all filtering after decisions by reloading persisted review cases instead of removing resolved rows from the local all-cases cache.
- Scoped Review count refreshes for affected GUI/repair flows and removed unsafe full-run count refreshes from hot paths.
- Replaced external best-lap identity sentinels with nullable identity values at the domain boundary and kept empty-string rendering only at CSV/PDF export edges.

### Validation

- Passed `python -m compileall -q forza`.
- Passed `python -m pytest -q -W error::ResourceWarning`.
- Passed `python -m forza maintenance db-upgrade`.
- Passed `python -m forza maintenance db-doctor --json` with `ok=true`.
- Passed `python -m forza --dry-run`.
- Passed a manual GUI workflow with a 10-image run and post-run audit covering DB state, logs, Review, and Best Laps.

---

## [0.15.5] - 2026-06-07

### Added

- Developer Tools now includes a `DB Maintenance` tab for controlled database fixers tied to known DB Doctor findings.
- Added archived Review duplicate scanning, preview, cleanup, and explicit Review case renumber actions.
- Added historical release record: `docs/history/2026-06-07_db_maintenance_review_cleanup_release.md`.

### Changed

- Review filters now operate on the cached Review queue after the initial database load instead of querying the database on every combobox change.
- Entering the Review section refreshes through the active view filters.
- Review case resolution advances by mutating the local queue instead of forcing a full DB reload.
- Review Case Queue no longer displays internal `Key` and `File` columns; these remain available in the selected case details.

### Fixed

- Archived Review duplicate rows with `business_key` values beginning with `duplicate:` can now be safely removed with backup after validation against their canonical Review case.
- Review cleanup can relink safe `review_corrections`, remove duplicate correction rows, and compact remaining Review case numbers to a contiguous sequence.

---

## [0.15.4] - 2026-06-07

### Added

- Deterministic imported-car canonicalization against `reference_cars` for
  external spreadsheet imports.
- New imported external car names from valid spreadsheet rows are added to
  `reference_cars`, even when those rows are not the final best external time for
  a track/class group.
- Best Laps now shows action/import summaries inside the active workflow, not
  only in the transient status bar.
- Historical release record:
  `docs/history/2026-06-07_best_laps_gui_read_service_release.md`.

### Changed

- Best Laps GUI table reads internal rows through
  `GuiReadService.list_laps(best_only=True)` instead of the generic
  `ExportLap`/PDF-CSV export read path.
- Active external records are read through the GUI read-facade session helper for
  the Best Laps screen.
- External spreadsheet import moved from Records to Best Laps.
- Records no longer exposes a separate External Records tab.
- `Generate PDF` and `Export CSV` in Best Laps now use the currently filtered
  table rows.
- Rebuild now recomputes relational derived state only. External spreadsheet
  import and PDF generation are explicit Best Laps actions.

### Fixed

- Imported external car spelling variants such as `Elemental Rp1 '19`,
  `Mini Cooper '65`, and `Toyota Corolla '74` no longer duplicate canonical car
  names in the Best Laps car filter.
- Best Laps import messages now report canonicalized cars, new cars, ambiguous
  cars, unmapped tracks, invalid laps, and a preview of newly added car names.

---

## [0.15.3] - 2026-06-07

### Added

- Permanent GUI visible-scope refresh contract.
- Background LM Studio model-list worker for Config Bench.

### Changed

- Developer Tools lazy-loads heavy tabs and uses stable tab containers.
- Developer Overview uses fast operational DB checks instead of full DB Doctor.
- Image Debug list/detail loading is selection-driven.
- Best Laps filters operate on cached in-memory rows after the first load.

### Fixed

- Developer Tools no longer loads DB Doctor, Config Bench model discovery, Model
  Debug, and logs at once.
- Developer Tools tab activation no longer skips after a lazy tab is loaded.
- Overview no longer reports Review legacy duplicate rows as fast-check DB errors
  when DB Doctor treats the database as healthy.
- Best Laps filters no longer require a full DB reload on every combobox change.

---

## [0.15.2] - 2026-06-06

### Changed

- Review refresh/upsert now uses only the current canonical `business_key`
  identity during normal runtime.
- Review candidate deduplication uses the same canonical key generated for
  persisted cases.
- `BestLapService` defers database-backed track ordering until first refresh.

### Fixed

- Transitional Review compatibility can no longer mask unrepaired legacy keys
  during normal refresh.

---

## [0.15.1] - 2026-06-06

### Added

- Logged `maintenance review-identity-repair` command with dry-run, apply,
  backup, and JSON output.
- DB Doctor checks for non-canonical Review keys and duplicate open Review cases.
- Stable `review_corrections` persistence and rebuild reapplication.
- Versioning contract and visible GUI version metadata.

### Changed

- Review refresh applies persisted corrections before candidate detection.
- Review case matching recognizes canonical and repair-compatible identities.
- Review decisions recompute affected best-lap frontier state.
- Lab Workbench refreshes opportunistically by active tab/workflow.
- GUI sizing and refresh contracts were clarified.

### Fixed

- Resolved dirty-lap cases no longer reappear after Review refresh.
- Gamertag and other Review decisions no longer leave stale pending best-lap
  state.
- Numeric-prefix Review detection catches 1-3 digit prefixes.
- Dirty-lap correction no longer invalidates best-lap groups incorrectly.
- Current Review/Image Detail/Ground Truth displays prefer corrected canonical
  values over stale model snapshots.
- DB Doctor detects stale pending best-lap state and non-canonical Ground Truth
  expected JSON.
- Review table sizing, CLI DB Doctor discoverability, image legacy-flag hiding,
  and review-case numbering were hardened.

---

## [0.15.0] - 2026-06-05

DB vNext hardening and documentation-structure release.

### Added

- Frozen SQL schema file for the DB vNext Alembic baseline.
- Permanent documentation policy, project status, contracts, architecture, user
  guides, developer guides, plans, and history directories.
- Review correction and DB vNext repository hardening plans.
- Abandoned-run recovery and expanded read-only DB Doctor checks.

### Changed

- Model attempts and artifacts persist incrementally and append-only.
- Prompt/model/export artifact reuse rejects divergent content or ownership.
- Rebuild globally and atomically regenerates best laps, system reviews, and
  system flags from relational state.
- Normal CLI/GUI startup requires explicit current schema.
- Best Laps separates source filtering from configured-player filtering.

### Fixed

- Run counters, interrupted-run state, LM Studio runtime snapshots, run-input
  representation, relational integrity handling, DB state enums, semantic batch
  rename, Model Debug evidence display, and GUI review/image behavior were
  hardened for DB vNext.

---

## [0.14.0] - 2026-06-04

DB vNext release. SQLite became the durable source of truth for discovery, model
attempts, review, flags, exports, lab state, and integrity checks.

### Added

- DB vNext SQLite architecture contract and implementation history.
- Clean Alembic vNext baseline.
- Run-input accounting, prompt snapshots, LM Studio runtime snapshots, extraction
  attempts, artifact integrity tracking, `--limit`, DB Doctor CLI/GUI checks, and
  normalized docs.

### Changed

- Codebase reorganized into explicit application/domain/pipeline/lmstudio/output/
  gui/lab packages.
- Legacy migration chain replaced by the DB vNext baseline for fresh runtime
  databases.
- Runtime persistence, run configuration snapshots, retry-errors, and suspicious
  time review comparison moved to the vNext model.

### Removed

- Legacy root modules, runtime SQLite files from version control, and obsolete
  worker-mode documentation.

### Fixed

- SQLite foreign keys, runtime health/config matching, duplicate compatibility
  properties, and DB Doctor output alignment.

---

## [0.13.0] - 2026-05-30

Reliability and GUI-contract consolidation release.

### Added

- `GuiConfigState`, config-aware GUI hooks, lazy major GUI sections, central Logs
  tab, debug checkbox, class/player Best Laps styling, runtime-reset preservation,
  hardened external-record import, cooperative parallel extraction, shared model
  request helpers, raw-response debug persistence, and developer maintenance docs.

### Changed

- Best-lap recomputation became explicit; SQLite runtime engines were hardened;
  navigation, Best Laps layout, settings, run config, runtime ETA, persistence,
  CLI status propagation, calibration, config saving, and schema upgrade behavior
  were consolidated.

### Removed

- Transitional config hooks, legacy backup/cache services, legacy runtime config
  fields, legacy alias format, and obsolete GUI ownership paths.

### Fixed

- Persistence failures, config propagation, rebuild/service freshness, prompt
  bench output paths, calibration UI, model-debug path safety, reference data
  tests, and warning-strict test behavior.

---

## [0.12.0] - 2026-05-26

GUI-first structural refactor. SQLite became the single runtime source of truth
for review, image management, best-lap state, and GUI actions.

### Added

- PySide6 GUI shell, SQL-backed Review actions, GUI rebuild workflow, Images page
  actions, image state toggles, disposable-file deletion guard, and SQL cleanup
  migration.

### Changed

- GUI refresh, table sizing, ReviewService, RebuildService, duplicate handling,
  physical deletion behavior, and Best Lap contribution semantics were converted
  to the GUI/SQL paradigm.

### Removed

- Manual override JSON workflow, generated review files, legacy review CLI,
  legacy override services/schemas, legacy review/image fields, obsolete runtime
  paths, hidden advanced image filters, and placeholder lab services.

### Fixed

- SQL Review decisions, Review case linkage, best-lap invalidation scope, worker
  shutdown cleanup, Prompt Bench DTOs, and GUI string normalization.

---

## [0.11.0] - 2026-05-24

CLI-only metadata foundation release.

### Added

- Consolidated Alembic schema, relational runtime tables, raw response
  persistence, raw-response debug fields, hash-based raw response naming,
  GUI read/write services, image rename service, event sink contract, relational
  best-lap frontier computation, and review linkage.

### Changed

- Runtime source of truth moved to SQLite relational tables; semantic filenames
  became metadata only; JSON snapshots/cache became artifacts rather than runtime
  state.

### Removed

- Operational dependency on cached results/laps, legacy snapshot cache APIs,
  legacy `SourceImage.path`, and automatic copy of review cases to calibration.

### Fixed

- Raw response path stability, raw response debug access, calibration candidate
  deduplication, dashboard aggregation, GUI service engine reuse, and Review case
  linkage.

---

## [0.10.0] - 2026-05-22

SQLite foundation hardening, Alembic integration, and GUI readiness sprint.

### Added

- Alembic runtime integration, `db-upgrade`, `db-check`, `db-current`,
  `config-check`, run lifecycle fields, database service boundaries, and engine
  lifecycle handling.

### Changed

- Run status separated from image extraction status and config validation occurs
  before processing.

### Fixed

- Early failures are traceable in run history, SQLite resource warnings were
  reduced, and event sink exceptions are isolated from the pipeline.

---

## [0.9.2] - 2026-05-19

### Fixed

- Raw-response fallback I/O error handling.
- Calibration timing accumulation.
- Dead variables and minor CLI cleanup.

---

## [0.9.1] - 2026-05-18

### Added

- Semantic filename system.
- Structured raw response files.
- Review cases for ambiguous tracks and weather.
