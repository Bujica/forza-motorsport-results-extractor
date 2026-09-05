# Fixtures

Status: current
Audience: developer, LLM
Lifecycle: permanent
Scope: what is versioned under `forza-rust/fixtures/` and what stays out of Git

Fixtures feed Rust tests and Python/Rust equivalence comparisons
(`docs/plans/2026-08-25_rust_migration_plan.md`, Fase 0). They come from the
Python 0.21.0-beta.1 baseline database.

## Versioned in Git (non-sensitive)

| Path | Content |
| --- | --- |
| `expected/` | Small sanitized expectations used by Rust unit tests (only synthetic or anonymized values). |
| `README.md` | This file. |

The migration-era `python_outputs/*.json` snapshots (schema inventory, counts,
reference catalog, run telemetry) were retired: nothing reads them (the schema
baseline lives frozen in `crates/forza-db/src/schema_ddl.rs` plus the
`frozen_schema_*` doctor checks; the reference catalog is compiled from
`forza-rust/assets/`), and local run telemetry has no place in a public repo.
See git history if they are ever needed again.

## Kept out of Git (personal or large)

These are generated locally for manual/equivalence comparison and must never be
committed:

- `images/` — real screenshots (personal data).
- `model_responses/` — sampled LM Studio raw responses including race results
  with opponent gamertags.
- `python_outputs/best_laps.csv`
- `python_outputs/best_laps.pdf`
- `python_outputs/artifacts/` — content-addressed export snapshots created by
  the Python export service.

`.gitignore` at the repository root enforces these rules.

## Expected-value fixtures

Small sanitized expectations used by Rust unit tests live in `expected/`.
Only synthetic or anonymized values may be committed there.
