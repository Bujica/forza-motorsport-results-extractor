# Database Contract Audit for the Rust Port

Status: current
Audience: developer, LLM
Lifecycle: permanent
Scope: integrity invariants of the Python baseline schema that `forza-db` must reproduce
Last verified: 2026-08-25
Source of data: `fixtures/python_outputs/schema_inventory.json` (machine-generated from the 0.21.0-beta.1 baseline DB)

This document records the persisted invariants found by auditing the baseline
schema. The Rust schema (`forza-db`, Fase 3) must reproduce every item here.
The authoritative narrative contracts remain `docs/contracts/database.md` and
`docs/contracts/review.md`; this file is the structural audit companion.

## Connection contract

Every pooled connection must initialize:

- `PRAGMA journal_mode=WAL`
- `busy_timeout` (value from config; default in code constants)
- `PRAGMA foreign_keys=ON`

The baseline schema relies on FK enforcement being ON at runtime.

## Partial unique indexes (business rules, not optimizations)

| Index | Table | Columns | Where clause | Rule |
| --- | --- | --- | --- | --- |
| `idx_attempts_one_accepted_per_result` | `extraction_attempts` | `(extraction_result_id)` | `accepted = 1` | At most one accepted attempt per extraction result. |
| `idx_runtime_one_preflight_per_run` | `model_runtime_snapshots` | `(run_id)` | `snapshot_kind = 'preflight'` | At most one preflight snapshot per run. |

Rust tests must cover both rules with positive and negative cases.

## Other uniqueness guarantees (implicit or explicit)

- `extraction_attempts`: unique `(extraction_result_id, attempt_number)`.
- `extraction_results`: unique `run_input_id`; unique `(run_id, image_file_id)`.
- `lap_records`: unique `(image_file_id, run_id, lap_index)` and unique
  `(extraction_result_id, lap_index)`.
- `review_cases`: unique `business_key`; unique `case_number`.
- `review_corrections`: unique `stable_key`.
- `reference_cars` / `reference_tracks`: unique `name`.
- `image_flags`: unique `flag_key`.
- `prompt_snapshots`: unique `(prompt_name, content_hash)`.

## ON DELETE action matrix

### CASCADE (child dies with parent)

| Child | Parent | Column |
| --- | --- | --- |
| `extraction_attempts` | `extraction_runs` | `run_id` |
| `extraction_attempts` | `extraction_results` | `extraction_result_id` |
| `extraction_results` | `extraction_runs` | `run_id` |
| `extraction_results` | `run_inputs` | `run_input_id` |
| `lap_records` | `extraction_results` | `extraction_result_id` |
| `lap_records` | `extraction_runs` | `run_id` |
| `external_lap_records` | `external_record_imports` | `import_id` |
| `model_artifacts` | `extraction_attempts` / `extraction_results` / `extraction_runs` | respective ids |
| `model_runtime_snapshots` | `extraction_runs` | `run_id` |
| `run_inputs` | `extraction_runs` | `run_id` |

Deleting a run therefore cascades through inputs, results, laps, attempts,
artifacts, snapshots. Deleting an image does NOT cascade (see SET NULL /
RESTRICT below).

### RESTRICT (parent cannot die while child exists)

| Child | Parent | Column |
| --- | --- | --- |
| `extraction_attempts` | `image_files` | `image_file_id` |
| `extraction_results` | `image_files` | `image_file_id` |
| `extraction_results` | `prompt_snapshots` | `prompt_snapshot_id` |
| `extraction_results` | `extraction_attempts` | `accepted_attempt_id` |
| `lap_records` | `image_files` | `image_file_id` |
| `image_flags` | `image_files` | `image_file_id` |
| `review_cases` | `image_files` | `image_file_id` |
| `review_corrections` | `image_files` | `image_file_id` |
| `extraction_runs` | `prompt_snapshots` | `prompt_snapshot_id` |

Images are protected by RESTRICT from every evidence table: deleting an image
row requires deleting its evidence first, which normal workflows never do
(files are marked `missing` instead).

### SET NULL (evidence survives, reference is dropped)

| Child | Parent | Column |
| --- | --- | --- |
| `export_artifacts` | `extraction_runs` | `run_id` |
| `extraction_attempts` | `model_runtime_snapshots` | `runtime_snapshot_id` |
| `image_flags` | `lap_records` / `extraction_results` / `extraction_runs` | respective ids |
| `review_cases` | `lap_records` / `extraction_results` / `extraction_runs` | respective ids |
| `review_corrections` | `review_cases` | `review_case_id` |
| `run_inputs` | `image_files` | `image_file_id` |
| `run_inputs` | `run_inputs` (duplicate_of) | `duplicate_of_input_id` |
| `model_artifacts` | `image_files` | `image_file_id` |
| `image_files` | `image_files` (duplicate_of) | `duplicate_of_image_file_id` |

Self-referencing `SET NULL` on `image_files.duplicate_of_image_file_id` means
deleting a canonical row detaches its duplicates instead of blocking.

## Check-constraint vocabularies (persisted enums)

These value sets are enforced by SQLite `CHECK`s and are part of the contract:

- `extraction_runs.status`: `pending, running, completed, failed, cancelled`;
  `mode`: `normal, dry_run`.
- `extraction_results.status`: `pending, running, ok, error, cancelled`.
- `extraction_attempts.status`: `ok, error, cancelled`; plus acceptance rule
  `(accepted = 1 AND status = 'ok') OR (accepted = 0 AND status <> 'ok')`.
- `review_cases.status`: `open, resolved, ignored, auto_resolved`;
  `outcome`: `pending, confirmed, model_error, ignored`;
  `reason`: `dirty_lap, track, weather, race_class, car, driver_name`;
  `trigger` and `decision_field` have enumerated nullable sets (see inventory).
- `review_corrections.field`: `dirty, track, weather, race_class, car, driver`;
  `cause`: `review, rebuild, auto, unknown`.
- `image_files.file_status`: `available, missing`;
  `best_lap_status`: `pending, contributing, non_contributing`.
- `image_flags.status/scope/flag_type`: enumerated sets (see inventory).
- `run_inputs.decision`: `process, skip, duplicate, missing, unsupported,
  outside_input...` (full set in inventory); `duplicate_kind`: `hash, batch`.
- `external_record_imports.status`: `pending, active, failed`.
- Numeric checks: non-negative sizes/counters, positive dimensions/workers,
  `best_lap_ms >= 0`, `lap_index >= 0`.

Full SQL for every constraint lives in `schema_inventory.json`
(`create_sql` per table). The Rust migration embeds equivalent definitions and
tests each vocabulary boundary.

## Triggers

The baseline has **no triggers**. All lifecycle logic lives in application
services. The Rust port must not introduce triggers silently.

## Derived vs review-authored state

Derived (recomputable, never user-edited):

- `lap_records.is_best_lap` (frontier recompute).
- `image_files.best_lap_status` (from winning frontier rows).
- `extraction_results.attempt_count` (denormalized counter).
- `extraction_runs` counters (`total_inputs`, `processed`, `succeeded`,
  `failed`, `skipped`, `duplicate_count`, `review_case_count`).
- All token/TPS/timing columns on attempts and results (measurement output).

Review-authored (user decisions that must survive rebuild):

- `review_cases.status`, `outcome`, and correction payloads.
- `review_corrections.*` (the source of truth for manual fixes reapplied by
  rebuild).

This distinction drives the rebuild contract: rebuild may regenerate derived
state globally but must preserve review-authored rows.

## Rust-side test checklist (Fase 3)

- [ ] both partial unique indexes: accept valid insert, reject second row;
- [ ] cascade path: delete a run, verify inputs/results/laps/attempts/
      artifacts/snapshots gone and images untouched;
- [ ] restrict path: attempt to delete an image with evidence fails;
- [ ] set-null paths: detach duplicate canonical, null out review case links;
- [ ] each vocabulary check boundary rejects invalid values;
- [ ] acceptance-status consistency check on attempts;
- [ ] WAL/busy_timeout/foreign_keys applied on every pooled connection.
