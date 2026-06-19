# Testing Policy and Execution Profiles

Status: current
Audience: developer, maintainer, LLM
Lifecycle: permanent
Scope: local test organization, execution profiles, coverage gates, and test-debt cleanup
Last verified: 2026-06-14
Related plan: `docs/history/2026-06-13_testing_policy_implementation_plan_archive.md`
Related tests: `python -m pytest -q`

This document defines the standing testing policy for the project. The implementation plan and sequencing live in `docs/history/2026-06-13_testing_policy_implementation_plan_archive.md`.

## 1. Baseline

The current audit baseline is:

```text
737 tests passing
87% total coverage
32.12s with coverage enabled on Windows/Python 3.11
```

This baseline is a control point. Test-organization changes must keep the full suite green and should not reduce total coverage below the accepted baseline unless the reduction is deliberate and documented.

## 2. Principles

1. Tests protect contracts, not incidental implementation details.
2. Local development needs a fast profile, but the full suite remains the release gate.
3. Static source-level tests are acceptable for architecture boundaries, removed shims, import rules, and clean-break compatibility guards.
4. Behavioral tests are preferred when a workflow can be tested without a full GUI interaction harness.
5. Database and integration tests should use minimal fixtures and shared builders where possible.
6. Test deletion must be conservative: merge or rewrite redundant tests before deleting them.
7. Coverage is a risk signal. Prioritize persistence, orchestration, parsing, model/runtime boundaries, and GUI service contracts over broad percentage chasing.
8. Test size is a maintainability contract. Split large files before they become broad catch-all suites.

## 3. Test layers

### static

Source-level or architecture-contract tests. These may read project files and assert that forbidden imports, removed aliases, or layer violations are absent.

Static tests should protect broad contracts, not freeze incidental formatting.

### unit

Pure or near-pure behavior tests. These should not require SQLite migrations, SQLModel sessions, live LM Studio, full Qt widgets, or heavyweight filesystem setup.

### db

Tests that create or use SQLite databases, migrations, SQLModel sessions, repositories, or application services backed by a real database.

### integration

Tests that exercise multi-service or end-to-end flows and intentionally cross multiple layers.

### gui_contract

Tests for GUI controllers, views, models, or wiring that do not require a live QApplication interaction harness. These may be static or fake-object behavioral tests.

### slow

Tests accepted as slower than the normal local feedback loop. A practical initial threshold is any test that regularly takes more than 1 second in isolation, or any file that dominates `--durations`.

## 4. Test naming convention

Names should make the test's role clear before reading the body. Markers define execution profile; names define intent.

### File names

Use this pattern for new files:

```text
tests/test_<area>_<contract>.py
tests/test_<area>_<contract>_static.py
tests/test_<area>_<workflow>_integration.py
```

Guidelines:

```text
test_<area>_<contract>.py
  Default for unit or focused behavior tests.

test_<area>_<contract>_static.py
  Source-level architecture, import-boundary, removed-shim, or schema-text guard.
  These files should normally receive the static marker automatically.

test_<area>_<workflow>_integration.py
  Multi-service or end-to-end workflow tests.
  These files should normally receive the integration marker automatically.

test_db_<contract>.py
  Database integrity, migration, repository, or SQLModel behavior.

test_gui_<surface>_<contract>_static.py
  GUI source-level contract tests that do not require QApplication.

test_gui_<surface>.py
  GUI-facing behavior tests with fakes or application services, not broad source scans.
```

Avoid names that describe chronology or implementation history rather than contract:

```text
test_new.py
test_misc.py
test_bugfix.py
test_cleanup.py
test_stage_four.py
test_final.py
```

Existing files do not need bulk renames. Rename only when already touching a file for cleanup or when the old name actively obscures the contract.

### Test function names

Use this pattern:

```text
test_<subject>_<expected_behavior>
```

Preferred examples:

```text
test_export_csv_writes_stable_relational_headers_and_rows
test_pdf_data_map_groups_and_sorts_rows_without_visual_snapshot
test_gui_debug_raw_evidence_prefers_sql_and_requires_explicit_artifact_read
test_lmstudio_runtime_request_retries_connection_error_then_returns_response
```

For negative and boundary tests, make the forbidden behavior explicit:

```text
test_gui_package_does_not_import_database_or_sqlmodel_directly
test_model_debug_controller_does_not_pass_raw_artifact_roots_for_normal_reads
test_rebuild_outputs_does_not_record_pdf_artifact
```

For static tests, prefer contract language over exact implementation wording:

```text
good: test_gui_read_write_services_are_qt_free_application_facades
avoid: test_source_contains_create_sqlite_engine
```

### Helper names

Use consistent helper prefixes:

```text
_make_<object>()
  Build an in-memory DTO/value object.

_seed_<state>()
  Create persisted DB state.

_fake_<dependency>() or _Fake<Dependency>
  Replace an external dependency.

_assert_<contract>()
  Shared assertion for a contract.

_read_<fixture>()
  Load test fixture data.
```

Examples:

```text
_make_export_lap()
_seed_valid_run()
_FakeSession
_assert_export_headers()
```

### Marker/name alignment

Names and markers should agree:

```text
_static.py          -> static
_integration.py     -> integration
test_db_*.py        -> db
test_gui_*_static.py -> static + gui_contract
```

A marker may be broader than a name when needed, but a misleading name should be corrected during normal cleanup.

### Cleanup rule

Do not create rename-only churn across the suite. Apply this convention to:

```text
new tests
tests already being rewritten
files touched during T3/T4/T5 cleanup
tests whose current names hide their role
```

## 5. Size and organization limits

The active test suite must stay small enough to audit quickly. The current hard
limit is enforced by `tests/test_docs_maintainability_static.py`:

```text
active test file: 650 lines maximum
active markdown doc: 550 lines maximum
```

New test files should normally stay below 250 lines. Treat 450 lines as a split
warning: before crossing it, move repeated setup into a helper or split by
contract area. A file may approach the 650-line hard limit only when it remains
cohesive and splitting it would make the contract harder to follow.

Do not keep comments or helper names that describe one-off generation scripts,
temporary patch batches, or old cleanup phases. Helpers should describe their
current test contract, not how they were originally produced.

For release patches that touch database schema, GUI-facing DB setup, or Best
Laps/external-record behavior, add at least one focused DB or service test that
creates a fresh database and exercises the current contract. Static string tests
may guard architecture, but they are not enough for user-visible persistence or
import regressions.


## 6. Planned pytest markers

Pytest configuration is stored in `pyproject.toml` under `[tool.pytest.ini_options]`.

Target marker taxonomy:

```toml
markers = [
    "static: source-level/static contract checks; no runtime behavior",
    "unit: pure or near-pure behavior tests without database-heavy setup",
    "db: tests that create/use SQLite, migrations, repositories, or SQLModel sessions",
    "integration: multi-service or end-to-end workflow tests",
    "gui_contract: GUI/controller/view contract tests without QApplication requirement",
    "slow: tests accepted as slower than the normal local feedback loop",
]
```

`--strict-markers` should be enabled only when this marker list is present and the suite has been checked for unknown markers.

## 7. Local execution profiles

Fast development loop:

```bash
python -m pytest -q -m "not db and not integration and not slow"
```

Static and GUI contract checks:

```bash
python -m pytest -q -m "static or gui_contract"
```

Database profile:

```bash
python -m pytest -q -m "db and not integration"
```

Integration profile:

```bash
python -m pytest -q -m "integration or slow"
```

Full gate:

```bash
python -m pytest -q
```

Coverage gate:

```bash
python -m pytest --cov=forza --cov-report=term-missing
```

Coverage should not be part of every local edit cycle. Use it before closing a milestone, before release work, or after deleting/rewriting tests.

## 8. Coverage gate

Initial policy:

```text
total coverage must stay at or above 87%
full pytest must stay green
coverage reductions require explicit justification in the commit message or review notes
```

Do not add tests only to improve low-risk coverage. Prioritize modules by release risk.

High priority:

```text
domain
schemas
db models and repositories
pipeline process/model_response
application services that persist or mutate data
LM Studio runtime boundary
DB Doctor integrity checks
export/report contracts
```

Medium priority:

```text
GUI read/write facades
GUI controllers with fake views/services
retention and maintenance services
external-record import behavior
```

Lower priority unless being changed:

```text
lab one-off tooling
diagnostic CLI presentation
manual workflow helpers
```

## 9. Test debt cleanup rules

### Keep

Keep tests that protect:

```text
schema/migration contracts
persistence integrity
public DTO or enum contracts
runtime boundary behavior
recent regressions or removed compatibility shims
broad architecture boundaries
```

### Merge

Merge tests when:

```text
multiple static tests read the same file for related tokens
two files protect the same alias-removal contract
per-screen GUI tests duplicate a global GUI boundary test
several DB tests repeat the same seed for one assertion each
```

### Delete

Delete tests only when:

```text
another test covers the same contract with the same failure mode
the protected legacy behavior no longer exists and a positive new-contract test remains
the test only freezes an internal string with no contract value
the test is obsolete and its removal keeps full pytest and coverage gates green
```

### Rewrite

Rewrite tests when:

```text
a static test can become a small behavioral test with fakes
a DB-heavy test can use a pure helper
a large integration fixture can be replaced by a focused builder
a UI wiring string test can become a controller-level fake-view test
```

## 10. Project script policy

The repository `scripts/` directory is currently treated as a local ignored scratch area for temporary patch/audit helpers. Do not introduce permanent project scripts there unless the repository policy and `.gitignore` are intentionally changed first.

For test profiles, prefer documented commands in this policy and in the active plan. If tracked command wrappers are needed later, decide a tracked location explicitly instead of relying on ignored scratch files.
