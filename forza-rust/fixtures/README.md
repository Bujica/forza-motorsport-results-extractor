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
| `python_outputs/schema_inventory.json` | Tables, columns, indexes (with partial `WHERE` clauses), foreign keys with `ON DELETE` actions, check constraints, triggers — extracted from SQLite. |
| `python_outputs/counts.json` | Row counts per table of the baseline database. |
| `python_outputs/reference_data.json` | Reference tracks and cars catalog rows. |
| `python_outputs/runs_performance_summary.json` | Per-run status/performance fields plus attempt aggregates (TPS, parse errors). No driver names. |
| `README.md` | This file. |

Regenerate with `py -3.11 tools/export_rust_baseline.py` from the repository
root (Python environment required).

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
