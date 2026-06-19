# Rebuild Contract

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: rebuild source of truth, derived-state regeneration, and idempotency
Last verified: 2026-06-05
Supersedes: rebuild rules embedded in DB vNext history files
Related tests: `tests/test_rebuild_integration.py`, `tests/test_cli_rebuild.py`, `tests/test_rebuild_static.py`

Rebuild regenerates outputs and derived state from current SQLite state without
calling the model.

## Source Rules

- Rebuild reads accepted relational extraction data.
- Rebuild does not use legacy JSON/cache files as canonical input.
- Rebuild must preserve manual review decisions unless the relevant contract
  explicitly says derived system rows are replaced.
- Manual review corrections must be keyed by stable identity that does not
  depend on `lap_record_id`, because rebuild may delete and recreate
  `lap_records`.
- After recreating derived lap rows, rebuild must re-link or re-apply preserved
  corrections by stable source/lap/field identity before reporting the rebuilt
  state as current.

## Derived-State Rules

Global derived state includes:

```text
lap_records.is_best_lap
system review cases
system image flags
exports
```

Derived state must be recalculated atomically and globally, not only for the run
that triggered the rebuild.

## Idempotency Rule

Running rebuild twice without changing inputs should not change derived row
counts or produce conflicting state.
