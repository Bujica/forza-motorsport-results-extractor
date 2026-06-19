# Developer Tools

Status: maintainer-only
Audience: maintainer, developer, LLM
Lifecycle: permanent index

These tools are not product runtime surfaces. They exist to inspect repository
health, diagnose local data, and prepare release evidence. A tool listed here may
be changed or removed without preserving user-facing compatibility.

## Supported

- `audit_db_vnext.py` - read-only SQLite runtime database inspection. DB Doctor
  remains the authoritative integrity gate; this tool is for human-readable
  drill-downs.
- `audit_module_size.py` - reports oversized source, test, documentation, and
  tool files by maintenance area.
- `diagnose_car_imports.py` - read-only diagnostic for imported Community
  Records car-name canonicalization.
- `run_release_audit.py` - local release evidence orchestrator for the current
  gates: compile, DB Doctor, module-size audit, pytest, targeted-test selection,
  and dry-run.
- `select_tests_for_changes.py` - focused pytest selector for local change sets.

## Temporary

- `audit_database_service_callers.py` - inventory for the remaining
  `DatabaseService` facade. Keep while service ownership is still being drained;
  remove after callers are stable or the facade is no longer a meaningful
  migration target.

## Discarded

The clean-break string audits and schema-drift helper were removed after the
0.17.0 clean-break. Their useful checks now live in product tests and DB Doctor,
and the old broad string scans produced false positives against negative tests
and deliberate current API names.
