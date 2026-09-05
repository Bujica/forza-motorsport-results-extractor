# Testing Policy and Execution Profiles

Status: current
Audience: developer, maintainer, LLM
Lifecycle: permanent
Scope: local test organization, execution profiles, quality gates, and test-debt cleanup
Last verified: 2026-09-05
Implementation: Rust (forza-rust/) — current. Legacy Python (forza/) frozen at 0.21.0-beta.1.
Related tests: `cargo test --workspace` (run from `forza-rust/`)

This document defines the standing testing policy for the project. The Rust
workspace in `forza-rust/` is the current product code; the Python tree in
`forza/` is frozen at 0.21.0-beta.1 and its `pytest` suite is legacy (Python CI
still runs `pytest` for the frozen tree, but it is not a gate for current
work).

## 1. Baseline

The current gate is:

```text
cargo test --workspace                      all green
cargo clippy --workspace --all-targets -- -D warnings     clean
cargo fmt --all --check                     clean
```

This baseline is a control point. Test-organization changes must keep the full
suite green. Coverage reductions or newly suppressed lints require explicit
justification in the commit message or review notes.

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

Pure or near-pure behavior tests. These should not require SQLite migrations, database sessions, live LM Studio, full GUI widgets, or heavyweight filesystem setup.

### db

Tests that create or use SQLite databases, migrations, repositories, or application services backed by a real database.

### integration

Tests that exercise multi-service or end-to-end flows and intentionally cross multiple layers.

### gui_contract

Tests for GUI workers, services, or wiring that do not require a live GUI interaction harness. These may be static or fake-object behavioral tests.

### slow

Tests accepted as slower than the normal local feedback loop. A practical initial threshold is any test that regularly takes more than 1 second in isolation, or any file that dominates test durations.

## 4. Test naming convention

Names should make the test's role clear before reading the body.

### File names

New Rust test targets live with their crate (`src/` unit tests or
`crates/<name>/tests/`). Use this pattern:

```text
<area>_<contract>.rs
<area>_<contract>_static.rs
<area>_<workflow>_integration.rs
```

Guidelines:

```text
<area>_<contract>.rs
  Default for unit or focused behavior tests.

<area>_<contract>_static.rs
  Source-level architecture, import-boundary, removed-shim, or schema-text guard.

<area>_<workflow>_integration.rs
  Multi-service or end-to-end workflow tests.

db_<contract>.rs
  Database integrity, migration, repository, or storage behavior.

gui_<surface>_<contract>.rs
  GUI-facing behavior tests with fakes or application services, not broad source scans.
```

Avoid names that describe chronology or implementation history rather than contract:

```text
new.rs
misc.rs
bugfix.rs
cleanup.rs
final.rs
```

Existing files do not need bulk renames. Rename only when already touching a file for cleanup or when the old name actively obscures the contract.

### Test function names

Use this pattern:

```rust
fn <subject>_<expected_behavior>()
```

Preferred examples:

```text
export_csv_writes_stable_relational_headers_and_rows
pdf_data_map_groups_and_sorts_rows_without_visual_snapshot
gui_debug_raw_evidence_prefers_sql_and_requires_explicit_artifact_read
lmstudio_runtime_request_retries_connection_error_then_returns_response
```

For negative and boundary tests, make the forbidden behavior explicit:

```text
gui_package_does_not_import_database_directly
model_debug_does_not_pass_raw_artifact_roots_for_normal_reads
rebuild_outputs_does_not_record_pdf_artifact
```

### Helper names

Use consistent helper prefixes:

```text
make_<object>()
  Build an in-memory DTO/value object.

seed_<state>()
  Create persisted DB state.

Fake<Dependency>
  Replace an external dependency.

assert_<contract>()
  Shared assertion for a contract.

read_<fixture>()
  Load test fixture data.
```

Examples:

```text
make_export_lap()
seed_valid_run()
FakeSession
assert_export_headers()
```

### Cleanup rule

Do not create rename-only churn across the suite. Apply this convention to:

```text
new tests
tests already being rewritten
tests whose current names hide their role
```

## 5. Size and organization limits

The active test suite must stay small enough to audit quickly.

```text
active markdown doc: 550 lines maximum
```

New test files should normally stay below 250 lines. Treat 450 lines as a split
warning: before crossing it, move repeated setup into a helper or split by
contract area. A file may grow beyond that only when it remains cohesive and
splitting it would make the contract harder to follow.

Do not keep comments or helper names that describe one-off generation scripts,
temporary patch batches, or old cleanup phases. Helpers should describe their
current test contract, not how they were originally produced.

For release patches that touch database schema, GUI-facing DB setup, or Best
Laps/external-record behavior, add at least one focused DB or service test that
creates a fresh database and exercises the current contract. Static string tests
may guard architecture, but they are not enough for user-visible persistence or
import regressions.

## 6. Fixtures

Fixtures live in `forza-rust/fixtures/`:

```text
expected/           committed golden expectations (synthetic or anonymized only)
model_responses/    git-ignored: sampled LM Studio raw responses (personal data)
images/             git-ignored: real screenshots (personal data)
```

Fixture tests that need the git-ignored personal data skip gracefully when it
is absent. Never commit real screenshots, raw model responses with opponent
gamertags, local databases, logs, or private spreadsheets.

## 7. Local execution profiles

All commands run from `forza-rust/`. Full gate:

```cmd
cargo test --workspace
```

Lints and formatting (both required clean before merge):

```cmd
cargo clippy --workspace --all-targets -- -D warnings
cargo fmt --all --check
```

Focused profiles:

```cmd
cargo test -p <crate>
cargo test -p <crate> <filter>
```

Clippy and fmt should be part of every local edit cycle; they are cheap and
they are gates. Use the full workspace suite before closing a milestone,
before release work, or after deleting/rewriting tests.

## 8. Quality gates

Standing policy:

```text
cargo test --workspace must stay green
cargo clippy --workspace --all-targets -- -D warnings must stay clean
cargo fmt --all --check must stay clean
gate regressions require explicit justification in the commit message or review notes
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
GUI worker/service facades
settings and rebuild services
retention and maintenance services
external-record import behavior
```

Lower priority unless being changed:

```text
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
the test is obsolete and its removal keeps the full gates green
```

### Rewrite

Rewrite tests when:

```text
a static test can become a small behavioral test with fakes
a DB-heavy test can use a pure helper
a large integration fixture can be replaced by a focused builder
a UI wiring string test can become a worker-level fake test
```

## 10. Project script policy

Temporary patch/audit helpers belong outside the tracked tree. Do not introduce
permanent project scripts unless the repository policy and `.gitignore` are
intentionally changed first.

For test profiles, prefer the documented commands in this policy. If tracked
command wrappers are needed later, decide a tracked location explicitly instead
of relying on ignored scratch files.
