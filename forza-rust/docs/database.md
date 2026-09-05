# Database

Status: current
Audience: developer, maintainer, LLM
Scope: `forza-db` — schema, migration, repositories, doctor, maintenance.

## Schema

- Engine: SQLite via rusqlite (WAL + busy timeout + FK enforcement, see
  `forza-db/src/connection.rs`).
- Version marker: `PRAGMA user_version`, currently `SCHEMA_VERSION = 2`
  (`forza-db/src/schema_ddl.rs`, frozen DDL — do not edit by hand).
- `migration::upgrade()` builds a fresh database from zero and refuses
  foreign versions. There is no auto-migration of old schemas; test databases
  are rebuilt.
- The `frozen_schema_*` doctor checks enforce the baseline at runtime.
- **Never open one sqlite file with both implementations.** Python and Rust
  schemas/versions differ; mixing them produces `Incompatible` errors by design.

## Key tables

`extraction_runs` (counters recomputed from rows, never trusted blindly) →
`run_inputs` (`INTEGER PRIMARY KEY AUTOINCREMENT`; `decision` process/skip/
duplicate/… with evidence columns) → `extraction_results` (exactly one per
process input) → `extraction_attempts` (accepted + history, raw evidence) →
`lap_records` (`is_best_lap` frontier flag) → `review_cases` (open/resolved/
ignored/auto_resolved) + `review_corrections` → `image_flags` (one active
system flag per open case) + `model_runtime_snapshots` (preflight) +
`reference_tracks/cars` (seeded from compiled assets).

## Repositories (`forza-db/src/repositories/`)

`runs` (inputs/results/attempts/counters/reconcile), `laps` (records,
`add_result`, rain-bucket candidates), `reviews` (candidate detection, upsert
preserving operator decisions), `corrections` (scoped apply), `flags`
(flag sync), `best_laps` (transactional frontier recompute), `images`,
`external_records` (atomic snapshot replace).

## Doctor (`forza-db/src/doctor.rs`)

`run_full_doctor` runs the ~70-check battery (integrity, run/input/result/
attempt evidence chains, images, reviews + flags, best laps, artifacts,
schema drift). It short-circuits to a `schema_head` failure off-head. Keep it
green: `forza.exe maintenance db-doctor`.

## History

The Fase-3 schema audit that drove this design lives in git history (and its
per-crate analysis in `migration/forza-db.md`); its invariants are now
enforced by the `frozen_schema_*` checks above, not by prose.

## Maintenance CLI

```
forza.exe maintenance db-status        # schema state + row counts
forza.exe maintenance db-doctor [--json]
forza.exe maintenance db-upgrade       # create fresh schema
forza.exe maintenance db-reset --yes   # delete DB files (refuses without --yes)
forza.exe maintenance db-heal          # backfill evidence + reconcile + counters
```
