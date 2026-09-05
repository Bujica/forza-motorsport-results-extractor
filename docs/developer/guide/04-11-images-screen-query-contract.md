# Developer Maintenance Guide: 11. Images-screen query contract

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: Developer maintenance guidance shard generated from the former oversized `guide.md` document
Last verified: 2026-09-05
Implementation: Rust (forza-rust/) — current. Legacy Python (forza/) frozen at 0.21.0-beta.1.

Back to index: [`../guide.md`](../guide.md).

## 11. Images-screen query contract

The Images screen uses facet-style filters. The displayed image list applies
all active filters. The inventory reads go through
`forza-db/src/gui_queries.rs` (`image_inventory` with `ImageInventoryFilter`:
file, best-lap, inventory, track, run, and processing-status filters plus an
include-missing flag).

Filter option dropdowns deliberately ignore their own active facet while
preserving the other active facets:

- Track options apply `file_status`, `processing_status`,
  `best_lap_status`, `inventory`, and `run_id`, but do not apply the
  current `track` filter.
- Run options apply `file_status`, `processing_status`, `best_lap_status`,
  `inventory`, and `track`, but do not apply the current `run_id` filter.

The `inventory` facet is an inventory-indicator facet, not a Review-reason
facet. It must not expose Review reasons such as `dirty_lap`, `track`,
`weather`, `race_class`, `car`, or `driver_name`.
Duplicate filtering must return complete duplicate groups: canonical row plus
duplicate rows, ordered so the group can be inspected and cleaned up together.

This lets the operator change a selected track or run without first clearing that same filter manually.

Run membership on Images is defined by `run_inputs.image_file_id`, not by
`lap_records`. A run that skipped, dry-ran, errored before valid laps, or only
classified duplicates still considered image files and must remain available in
the Images Run filter when the other facets match.

Do not compute these option lists by loading all `lap_records` or all
`image_files` into the GUI layer. The inventory query owns this and must use
SQL-level filtering (filtered ID set first, then chunked `IN` fetches past the
SQLite variable limit, with the derived status resolved via a status map) so
large databases do not block the GUI during refresh.

`processing_status` is a read-model facet for Images. It is derived from the
latest `extraction_results.status` per image file plus the latest `run_inputs`
decision when no result exists. No result and no skipped latest input is
`unprocessed`; latest `pending`/`running` is `processing`; latest terminal
results map to `processed_ok`, `processed_error`, or `cancelled`; latest
non-process run input with no result is `skipped`. Do not persist this as a
second lifecycle column on `image_files`.

Inventory sync goes through `ImageInventoryService::sync_input_folder`: it
registers supported files found in the configured input directory, updates
inventory state, and never contacts the model or creates a run. A different
file now occupying a known path must not rewrite the existing row's identity
in place: the old owner is retired to `missing` and a fresh row is inserted,
so past `extraction_results`/`lap_records` references stay intact.

Image detail reads live in `image_detail.rs`; the supported GUI diagnostic
path for selected image/result evidence is `image_debug.rs` (500-row case
fetch, per-result detail plus a preflight runtime tab). Both read
accepted/latest relational evidence rather than recomputing extraction state
in the view.

## 12. Diagnostics contracts

Diagnostics keeps product-adjacent diagnostic and maintenance surfaces only:

- Diagnostics tabs are: Overview, Image Debug, DB Doctor, and Logs.
- Overview combines LM Studio runtime status with DB Doctor and product
  inventory counts.
- Overview LM Studio details are derived from the non-mutating preflight
  snapshot and remain read-only. The view renders endpoint, configured model,
  configured LM Studio request/load/image settings, runtime policy, loaded
  instance, effective loaded runtime config, capabilities, model metadata, and
  warnings; it must not trigger model loads itself.
- Image Debug is the supported GUI diagnostic path for selected image/result
  evidence. It must read accepted/latest relational evidence through the
  image-debug queries rather than recomputing extraction state in the view.
- DB Doctor is the canonical relational integrity check before reruns and
  releases. It is read-only and checks schema head plus invariants: SQLite
  integrity/foreign keys, abandoned runs, relational run counters, input
  decision/reason contracts, final-result state, accepted-attempt linkage,
  attempt parent/runtime/count relationships, model/raw/failed-attempt/export
  artifact integrity, prompt/runtime snapshots including deterministic prompt
  id/hash and run linkage, redacted and recomputable request payloads, stable
  review/flag keys, orphan rows, best-lap status including stale pending
  images, expected-result JSON shape, and effective schema column/default
  drift.
- Conclusive Doctor results apply to quiescent/reconciled databases. While a
  run is active, running-run, counter, and process-input/result checks are
  expected to report unfinished work.

## 13. Database and migrations

Migration policy:

- The Rust line owns its own schema; there is no data migration from
  unmanaged or obsolete local databases, and one SQLite file must never be
  shared between the Rust and Python implementations. Use the GUI-confirmed
  reset or `forza.exe maintenance db-reset --yes` before
  `forza.exe maintenance db-upgrade` when switching an old runtime workspace.
- `forza.exe maintenance db-upgrade` creates schema v2 (stamped into
  `PRAGMA user_version`; the frozen baseline lives in
  `crates/forza-db/src/schema_ddl.rs` plus the `frozen_schema_*` doctor
  checks). Future schema changes add versioned migrations.
- Migrations must not build the schema from current code metadata; the
  baseline executes frozen DDL.
- Keep migration execution explicit through maintenance commands.
- GUI startup can prompt before creating/upgrading/resetting the configured
  database. CLI runtime startup can check schema state and fail clearly, but
  must not auto-upgrade.
- Read-only schema/status checks must remain read-only and avoid mutable
  SQLite pragmas.

Runtime durability rules:

- Persist a result shell before image encoding/chat work.
- Append every real model attempt and its integrity-tracked artifact as soon
  as the call completes; never delete/recreate attempt history.
- Treat prompt snapshots and registered model/export artifact snapshots as
  immutable. Reuse verifies identity, payload, hash, size, and ownership and
  fails on divergence instead of silently replacing evidence.
- Finalize and commit each image before pause/cancel checkpoints.
- Never swallow relational integrity errors; fail and reconcile the run
  instead of treating an unknown constraint failure as a duplicate.
- Refuse `status='completed'` while any process input lacks a result or any
  result remains pending/running.
- Exclude paused duration from elapsed/rate metrics.
- Reconcile abandoned running runs before starting new work.
- Rebuild best laps, system reviews, and system flags globally and atomically.

Before changing schema-dependent services:

1. Update the frozen DDL / migration step.
2. Update repositories and services.
3. Add tests for the migration-sensitive behavior.
4. Update docs if runtime state semantics changed.

## 14. Review, image, and best-lap semantics

Identity and state rules:

- `image_file_id` is physical screenshot file identity.
- `file_hash` groups identical content but does not collapse physical files.
- `semantic_name` is presentation metadata, not identity.
- Renaming a fully selected semantic series assigns `Race NNN` chronologically
  from persisted `race_datetime`, falling back to physical file modified time.
  Partial selections preserve valid existing numbers. Batch swaps use temporary
  same-directory names before one transactional SQL path update.
- Duplicate images are represented relationally, not by automatic folder moves.
- `review_cases` and `image_flags` are SQL state, not override files.
- Review uses canonical reasons: `dirty_lap`, `track`, `weather`,
  `race_class`, `car`, `gamertag`, and `driver_name`. More specific
  suspicion sources belong in `review_cases.trigger`.
- Review refresh applies persisted `review_corrections` before candidate
  generation. Rebuild and normal refresh must agree on this ordering.
- A corrected review is persisted as `outcome='model_error'` with
  `decision_field`, `model_value`, and `corrected_value`. Diagnostics should
  use that outcome for improvement samples.
- Physical deletion is allowed only through explicit selected-image Delete in
  the GUI.
- GUI Delete removes the physical file when it is inside the configured
  `input_dir` and removes the related image database records. Delete is
  two-step (arm, then Confirm).
- If the selected physical file is already missing, Delete still removes the
  related image database records.
- `missing` is reserved for files that disappear outside an explicit GUI delete
  action.
- Files outside configured `input_dir` must never be physically deleted by GUI
  image Delete actions.

Best-lap rules:

- Internal screenshot rows come from persisted `lap_records.is_best_lap` state.
- External rows are active community records read from SQL.
- External records do not create fake `image_file_id`, `run_id`, or `lap_records` entries.
- Recompute/rebuild is explicit. Read-only screens and services must not silently mutate best-lap state.
- GUI Review decisions that change `dirty`, `gamertag`, `car`, `track`,
  `weather`, or `race_class` must recompute the persisted frontier before
  reporting the correction complete.

## 15. Reference data and external records

Canonical files:

```text
reference_cars
reference_tracks
data/external/track_aliases.json
data/external/DataFM.xlsx
```

Rules:

- Runtime references live in SQLite; standalone reference text files are seed/test inputs only.
- Track/reference ordering is alphabetical by name.
- Hardcoded domain subsets must stay aligned with those files.
- Track layouts are layout-specific and should not be merged casually.
- External record import must validate CSV/XLSX structure, required fields, aliases, malformed rows, invalid lap times, unmapped tracks, and row limits, then activate the accepted snapshot in SQL.
- Missing or invalid alias files should be observable through warnings/issues, not silent behavior.
- A failed external import must not replace the active external-record snapshot.

## 16. Adding a new GUI feature safely

Use this checklist:

1. Decide whether the feature is read-only, mutating, or long-running.
2. Put persistence operations behind existing services or add a new
   service/use case in `forza-app`.
3. Keep the view signal-oriented; do not put database or business logic in the
   widget/UI files.
4. If long-running, run it on the worker path and pass a start-time config
   snapshot (`RunParams`-style), never live mutable config.
5. Emit events or mark sections dirty so other pages reload canonical state.
6. Add regression tests for the contract being protected.
7. Update this guide if the feature adds or changes a GUI-wide rule.

## 17. Adding a new service/use case safely

Use this checklist:

1. Define input/output types if the service boundary needs stable structure.
2. Keep repository access inside service/application layers.
3. Do not mutate caller-owned data unless that is the explicit contract.
4. Make failure modes explicit and observable.
5. Add tests for success, failure, and boundary behavior.
6. Update CLI/GUI adapters only after the service contract is stable.

## 18. Common maintenance tasks

Database maintenance (run from `forza-rust/`, binaries are `forza.exe` CLI
and `forza-gui.exe` GUI):

```cmd
forza.exe maintenance db-status
forza.exe maintenance db-upgrade
forza.exe maintenance db-doctor --json
forza.exe maintenance db-doctor
forza.exe maintenance db-heal
```

Runtime cleanup:

```cmd
forza.exe maintenance db-reset --yes
```

Normal user-facing commands:

```cmd
forza-gui.exe
forza.exe run
forza.exe run --dry-run
forza.exe run --limit 5
forza.exe run --force
forza.exe run --retry-errors
forza.exe rebuild
forza.exe export
forza.exe export --pdf
forza.exe config-check
```

A cancelled CLI run exits with code 130.

## 19. Pre-merge checklist for `dev -> main`

Before merging `dev` into `main`:

1. Confirm `dev` is not behind `main`.
2. Confirm the working branch has no unintended generated artifacts.
3. Run the Rust validation gates: `cargo test --workspace`,
   `cargo clippy --workspace --all-targets -- -D warnings`, and
   `cargo fmt --all --check`.
4. Smoke-test GUI startup (`forza-gui.exe`).
5. In the GUI, save a Settings change and confirm config-sensitive views update without restart.
6. Start a dry run from Process and confirm it uses the saved config.
7. Run or inspect Diagnostics tabs when GUI diagnostics, DB Doctor, or logs changed.
8. Confirm `docs/project_status.md`, the relevant `docs/contracts/` file,
   `QUICK_GUIDE.md`, `docs/user/guide.md`, `docs/user/advanced_tools.md`, and
   this guide still describe the code that exists.
9. Confirm the version and changelog are appropriate for the merge.
10. Merge only after any local validation gaps are explicit.

## 20. Documentation map

Read these files before large maintenance changes:

- `docs/project_status.md`: current stage, known issues, and next approved work.
- `docs/documentation_policy.md`: documentation naming, lifecycle, ownership, changelog, and update rules.
- `docs/contracts/README.md`: index of normative behavior contracts.
- `docs/contracts/versioning.md`: version source of truth, bump policy, and
  release checklist.
- `docs/architecture/README.md`: index of current structural architecture documents.
- `QUICK_GUIDE.md`: quick install, launch, common commands, and documentation entry points.
- `CHANGELOG.md`: release history; stays at repository root by convention.
- `docs/README.md`: documentation index.
- `docs/user/guide.md`: full external user manual.
- `docs/user/advanced_tools.md`: advanced GUI diagnostics, DB Doctor, logs, and generated-artifact notes.
- `docs/history/README.md`: explains which historical records are published and
  why pre-beta archives are not part of the public repository.
- `forza_config.ini.example`: default user-editable configuration shape.

When code and docs disagree, inspect the relevant contract and
`docs/project_status.md`. Contracts define intended behavior, project status
records known issues, and implementation changes must update both when the intended
behavior changes.

## Raw flag API is not part of the Images query contract

The Images screen query contract does not include a raw image flag list or manual raw flag mutation surface. Do not reintroduce a normal-GUI `image_flags` internal SQL evidence path for image management.

The controller-facing filter is inventory-oriented. If an internal read-query parameter is still named `flag`, only the product inventory value `duplicate` is meaningful there; Review reasons such as `track`, `weather`, `race_class`, `car`, or `driver_name` must not filter the Images inventory.

Debugging raw `image_flags` evidence belongs behind an explicit Diagnostics contract. Until such a contract exists, the supported user-facing paths are Images inventory, Image Detail Review cases, Review queue, and Image Debug extraction evidence.
