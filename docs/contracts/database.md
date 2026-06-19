# Database Contract

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: SQLite runtime source of truth and integrity contract
Last verified: 2026-06-16
Supersedes: database contract sections in `docs/DEVELOPER_GUIDE.md`
Related tests: `tests/test_db_doctor_core_service.py`, `tests/test_db_repositories_core.py`, `tests/test_db_vnext_runtime_contracts.py`

SQLite is the operational source of truth. Runtime screens, rebuild, export,
review, and Developer Tools must read relational state and registered artifacts,
not legacy JSON snapshots or cache files.

The full architecture and table-level schema live in
`docs/architecture/database.md`. This contract summarizes the behavior that code
must preserve.

## Reset Boundary

The Images-first schema reset starts from a clean database. There is no migration
requirement from earlier local DBs. CLI `db-reset`, GUI-confirmed reset, and
new database creation must build the new baseline directly; compatibility
tables, views, aliases, and columns from earlier runtime designs must not be
retained only to preserve old data.

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

`python -m forza maintenance db-doctor --json` is the main database integrity
gate. A passing DB Doctor report proves only the checks it implements; it does
not replace workflow-specific contract tests.

DB Doctor must block release/rerun confidence when Review business keys are not
canonical, when open Review cases lack matching active flags, or when relational
runtime evidence no longer matches the frozen schema contract.

Historical repair scripts are not product runtime surfaces. If a future
database cleanup is needed, it must be implemented as a current, reviewed
maintenance path with an explicit backup and validation plan.
