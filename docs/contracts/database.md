# Database Contract

Implementation: Rust (forza-rust/) — current. Legacy Python (forza/) frozen at 0.21.0-beta.1.
Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: SQLite runtime source of truth and integrity contract
Last verified: 2026-09-05
Supersedes: database contract sections in `docs/DEVELOPER_GUIDE.md`
Related tests: unit/integration tests in `forza-rust/crates/forza-db`

SQLite (via `rusqlite`) is the operational source of truth. Runtime screens,
rebuild, export, review, and Developer Tools must read relational state and
registered artifacts, not legacy JSON snapshots or cache files.

The full architecture and table-level schema live in
`docs/architecture/database.md`. This contract summarizes the behavior that code
must preserve.

## Schema Version And Migration

- Schema identity is `PRAGMA user_version`; the current build expects
  `SCHEMA_VERSION = 2` (`forza-db/src/schema_ddl.rs`).
- `forza-db/src/migration.rs::upgrade()` builds the full schema from zero
  inside one transaction (tables + indexes from `schema_ddl.rs`, plus
  Images-inventory performance indexes), then stamps `user_version`, seeds
  the reference catalog, and backfills performance indexes. Re-running on a
  current database is a no-op (seed + backfill only).
- `upgrade()` refuses populated databases with a foreign version instead of
  migrating them: the Rust line creates its own databases from zero.
  Python-created databases are never opened in production.
- The runtime database must never be shared between implementations.
- `schema_ddl.rs` is frozen DDL; the `frozen_schema_*` DB Doctor checks
  enforce that runtime databases still match it.

## Reset Boundary

The Images-first schema reset starts from a clean database. `forza.exe
maintenance db-reset --yes` deletes the configured SQLite database (after an
exclusive-lock check), and `db-upgrade` / new database creation builds the new
baseline directly; compatibility tables, views, aliases, and columns from
earlier runtime designs must not be retained only to preserve old data.

During the transition, implementation files may still contain old table names,
but the approved target identity is:

- `image_files` stores one observed physical file per row.
- `image_files.current_path` is persisted and exposed as a string path; callers
  convert to `Path` only where a filesystem operation requires it.
- `file_hash` identifies identical bytes and is indexed, not unique.
- `run_inputs` records every file considered by a run.
- model evidence, laps, review cases, flags, and artifacts link to the physical
  image-file identity, not to content hash alone.
- Duplicate file relationships and active duplicate flags are maintained by scan
  and delete reconciliation, not by hidden or disposable lifecycle states.
- `image_files.image_metadata_json` is raw decoder metadata retained for
  post-processing analysis only; it is not operational runtime state.
- `image_flags` is internal/system state used for derived flags, integrity
  checks, and duplicate/review linkage. Review cases are the normal
  operator-facing surface for revisable findings; raw flags must not become
  primary Images or Image Details UI.

## Core Rules

- Every considered input must have a `run_inputs` row.
- Every supported physical image in the configured input folder must be able to
  appear in Images before extraction.
- Run-level operational failures must not create per-image extraction errors.
- Successful extraction results must point to an accepted attempt.
- Accepted attempts must retain raw model evidence in the database or through a
  canonical `model_artifacts` row.
- Prompt and runtime state must be immutable evidence linked to runs and
  attempts.
- `lap_records` is the canonical extracted lap table.
- `review_cases` and `image_flags` are SQL state, not override files.
- `review_cases.business_key` must be either current canonical Review identity
  or a superseded review key. Legacy keys must be repaired by a maintenance
  command, not by manual SQL edits.
- `review_corrections` stores approved model-error corrections by stable
  source/lap/field identity so rebuild can re-apply them after recreating
  volatile lap rows.
- Best-lap state, system review cases, and system flags are derived and
  rebuildable from accepted relational results plus preserved manual decisions.
- Redundant best-lap views or tables must not be kept unless an implemented
  read path uses them and measured performance requires them.

## Integrity Gate

`forza.exe maintenance db-doctor [--json]` is the main database integrity
gate. A passing DB Doctor report proves only the checks it implements; it does
not replace workflow-specific contract tests.

DB Doctor must block release/rerun confidence when Review business keys are not
canonical, when open Review cases lack matching active flags, or when relational
runtime evidence no longer matches the frozen schema contract.

Related maintenance commands (`forza.exe maintenance ...`):

```text
db-status          inspect schema state and row counts (read-only)
db-doctor [--json] run relational integrity checks (read-only)
db-upgrade         create the database from zero (refuses foreign versions)
db-reset --yes     delete the configured database (exclusive-lock checked)
db-heal            backfill missing extraction evidence left by older builds
```

## SQLite File-Size Maintenance

`DELETE` removes relational rows but does not normally shrink the SQLite file.
SQLite keeps the released pages in its freelist so later inserts can reuse them.
The physical file size is therefore not expected to decrease after every image
cleanup.

Routine cleanup must not run `VACUUM` after each deletion. After a large,
intentional deletion, a maintainer may reclaim unused pages with `VACUUM` only
when the application is closed and an explicit backup has been created.

Before and after `VACUUM`, run `forza.exe maintenance db-doctor --json`
and retain the backup until the post-maintenance checks pass. Do not delete the
SQLite `-wal` or `-shm` sidecars independently, and do not treat file size alone
as an integrity signal; use SQLite integrity checks and DB Doctor instead.

Historical repair scripts are not product runtime surfaces. If a future
database cleanup is needed, it must be implemented as a current, reviewed
maintenance path with an explicit backup and validation plan.
