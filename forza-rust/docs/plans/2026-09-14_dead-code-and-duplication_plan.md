# Dead-code removal and duplication-unification plan

Status: planned
Audience: maintainer, developer, LLM
Lifecycle: permanent (until completed, then moved to `../history/`)
Scope: deleting verified-dead code and unifying duplicated logic found in
the 2026-09-14 residue audit (no behavior change unless a phase says so).
Last verified: 2026-09-14
Supersedes: nothing
Related tests: `cargo test --workspace` must stay green; goldens
(`domain_golden`, `output_golden`, `pdf_render`, `response_golden`)
must remain byte-identical in every phase.

> Project language rule: all project files (code, docs, comments, commit
> messages) are written in English. This plan follows that rule.

## Working agreements (apply to every phase)

1. **Prove dead before deleting.** For each deletion, the phase lists the
   `rg` query that proves zero live callers; re-run it at implementation
   time. Test-only callers do not count as live, but removing a variant
   used by tests requires updating or deleting those tests in the same
   change.
2. **Behavior preservation first.** Unifications must keep goldens
   byte-identical. Where two copies already disagree (flagged below),
   the phase picks the documented-canonical semantics, adds a pinning
   test, and calls out the change in `CHANGELOG.md`.
3. **Gate per phase, before moving on:**
   `cargo fmt --all --check`,
   `cargo clippy --workspace --all-targets -- -D warnings`,
   `cargo test --workspace`.
   Slint (`.slint`) edits additionally require `cargo check -p forza-gui`
   (the Slint compiler runs in `build.rs`); SQL edits require the
   `doctor_full` + `gui_inventory` + `decide_outcome` suites plus a manual
   `db-doctor` run on a real database when the query shape changes.
4. **One phase per commit**; message names the phase
   (e.g. `Remove dead service wrappers (residue phase 2)`).
5. Update the topic doc in the same change when behavior or workflow
   changes; `CHANGELOG.md` Unreleased entries for user- or
   maintenance-visible changes (pure deletions of dead code get one
   shared entry, not one per item).
6. When this plan is fully implemented, move it to `../history/` as a
   dated record and list it in `../history/README.md`.

## Execution order

Phase 1 → Phase 2 → … → Phase 7, ordered by risk (pure deletions
first, semantic unifications after). Any phase may be deferred
explicitly in the history record. Phase 8 is documentation-only and may
land with any phase.

---

## Phase 1 — Dead CLI surface (`--debug`, binary `pub`, homonyms)

**Findings.**
- `forza-cli/src/main.rs:143`: `let _ = debug;` — the `--debug` flag is
  parsed and discarded; it never influences logging or config.
- `forza-cli/src/main.rs:9` (`pub const APP_VERSION`) and
  `forza-cli/src/commands/mod.rs:3-9` (`pub mod …`): `pub` inside a
  `[[bin]]` crate is unreachable externally.
- Same-name confusion: `cli/commands/common.rs:31`
  `table_count(conn, name) -> Option<i64>` (row count) vs
  `db/migration.rs:23` `table_count(conn)` (table count).

**Steps.**

1. Decide `--debug`: either wire it (e.g. set `RUST_LOG=debug` via
   `tracing-subscriber` before dispatch, matching the GUI's `EnvFilter`
   behavior) or delete the flag and the binding. Wiring is preferred
   only if a manual CLI run confirms the output changes; otherwise
   delete — a dead flag is worse than no flag.
2. Demote binary `pub` to private (`const APP_VERSION`, `mod …`);
   `pub(crate)` items in `commands/common.rs` are already correct, leave
   them.
3. Rename one homonym (suggested: `common.rs` → `table_row_count`,
   keep `migration.rs::table_count`). Update the 1–2 call sites.
4. Verify: `rg "pub (const|mod)" crates/forza-cli/src` shows nothing
   outside `pub(crate)`; `cargo build -p forza-cli` clean.

**Acceptance.** CLI `--help` output reviewed (flag either works or is
gone); no test references the removed items; gate green.

---

## Phase 2 — Dead service wrappers and test dummies

**Findings.**
- `forza-app/src/services/mod.rs:166` `run_doctor` and `:289`
  `fast_db_report` (path version): zero callers — all call sites use
  `run_full_doctor_on_path` and `fast_db_report_from_conn`. Both are
  re-exported in `forza-app/src/lib.rs:32-35`.
- `forza-output/tests/pdf_render.rs:7,262`: `use std::path::Path` exists
  only for `let _ = Path::new("unused");`.
- `forza-lmstudio/examples/lm_health.rs:39`:
  `let _ = NormalizedLoadConfig::default();` with unused output.

**Rules:** dead code is a reading-tax and a wrong-example risk; delete,
do not `allow`.

**Steps.**

1. Delete `run_doctor` and the path-taking `fast_db_report` plus their
   `lib.rs` re-exports. Re-run the zero-caller queries at
   implementation time (`rg "run_doctor\("`, `rg "fast_db_report\("`
   excluding `fast_db_report_from_conn`); if a caller appeared since the
   audit, stop and re-scope instead of deleting.
2. Delete both dummy lines in `pdf_render.rs` (import + statement) and
   the discarded `NormalizedLoadConfig::default()` line (plus the import
   if it becomes unused).
3. Verify: full workspace `cargo test` (lib re-export removal breaks
   downstream callers at compile time — the compiler is the check).

**Acceptance.** `rg` queries from step 1 return only history/plan
mentions; gate green.

---

## Phase 3 — Dead GUI request variant and unused domain helper

**Findings.**
- `forza-gui/src/worker.rs` `Request::RunDoctor`: handled, but no
  callback ever sends it — the only sender is
  `forza-gui/tests/worker_round_trip.rs:279`. Production path uses
  `RunFullDoctor` (`callbacks/maintenance.rs:14`).
- `forza-domain/src/text_utils.rs:7`
  `normalize_whitespace_lower`: only its own `#[cfg(test)]` uses it;
  production uses `normalize_ascii_compare` (via `normalizer.rs:58`).

**Steps.**

1. `RunDoctor`: check with the maintainer whether any external driver
   (script, docs) sends it; default is delete the variant + handler +
   test sender, keeping `RunFullDoctor`. If kept, document why in a
   comment on the variant (it then stops being residue).
2. Demote `normalize_whitespace_lower` to `#[cfg(test)]` (keeps the
   unit tests meaningful) or delete it with its tests if the coverage
   duplicates `normalize_ascii_compare` tests.
3. Verify: `cargo test -p forza-gui` (round-trip suite covers the worker
   protocol end to end).

**Acceptance.** No `Request::` variant without a production sender;
`rg normalize_whitespace_lower` shows test-only scope; gate green.

---

## Phase 4 — Unify `int_or_none` (divergent duplicate)

**Finding.** Same name, same purpose, different semantics:
`forza-lmstudio/src/load_config.rs:47` handles `u64` via wrapping `as`
and trims strings; `forza-lmstudio/src/client.rs:94` returns `None` for
`u64 > i64::MAX` and parses untrimmed. A large `size_bytes`/`context`
value parses differently depending on which module reads it.

**Rules:** `api-single-owner`, `num-cast-try-from` (no wrapping `as`).

**Steps.**

1. Move one implementation to a shared home both modules already reach
   (both live in `forza-lmstudio`; e.g. `load_config::int_or_none` made
   `pub(crate)`), with the union semantics: trim strings (superset of
   both current behaviors) and saturate `u64` via
   `i64::try_from(u).unwrap_or(i64::MAX)` (never wrap, never drop to
   `None` for in-range values).
2. Delete the `client.rs` copy; update its call sites (unchanged
   signatures).
3. Add a unit test pinning the union semantics, including
   `u64::MAX`, padded `" 42 "`, and non-numeric strings. Existing
   `summaries_match_python_format` and `response_golden` must stay
   green (they pin the currently-observed outputs).
4. Verify: `rg "fn int_or_none"` returns exactly one definition.

**Acceptance.** One definition; new test green; golden suites unchanged
(or, if a golden changes, the divergence is documented as a fixed bug
with a `CHANGELOG.md` entry — not silent).

---

## Phase 5 — One `placeholders(n)` helper (11 copies)

**Finding.** Identical `*.iter().map(|_| "?").collect::<Vec<_>>().join(",")`
in `db/gui_queries.rs` (4), `db/image_debug.rs` (3),
`db/repositories/best_laps.rs` (2), `db/repositories/flags.rs`,
`app/image_rename.rs` (plus `placeholders2` in `gui_queries.rs:319` —
check whether it differs before merging).

**Rules:** `api-single-owner`; note `BIND_CHUNK_SIZE`/`id_chunks`
already centralize the *chunking* limit in `db/lib.rs:38` — this helper
centralizes the *placeholder* rendering next to it.

**Steps.**

1. Add `#[must_use] pub fn placeholders(n: usize) -> String` in
   `forza-db/src/lib.rs` (next to `id_chunks`), implemented without
   intermediate allocation (`"?,".repeat(n)` trimmed, or equivalent).
2. Replace all 11 sites (plus `placeholders2` iff identical) with the
   helper. No signature changes anywhere.
3. Verify: `rg 'map\(\|_\| "\?"' crates` returns nothing; full `db` +
   `app` suites green (generated SQL text is identical by construction).

**Acceptance.** Single definition; zero SQL-text change (diff the
generated strings in a test if cheap — otherwise rely on the unchanged
query test suites).

---

## Phase 6 — Unify lap-row projection (dual traits + parallel structs)

**Finding.** Two 6-field projection traits for the same logical row:
`FrontierLap` (`domain/frontier.rs:11`) vs `LapRowLike`
(`domain/ordering.rs:8`), plus parallel structs
(`BestLapRow`, `LapExportRow`, `DetailLapRow`, `ExportRow`, `PdfRow`,
`PdfExternalRecord`, `ExternalLapRecord`, test-only `laps.rs:433
BestLapRow`) with hand-written converters (`row_from_export`,
`row_from_external`, `to_export_rows`, `to_external_pdf_records`,
manual `ExportRow{}` in `cli/export.rs:25`,
`PdfExternalRecord{}` in `callbacks/bestlaps.rs:263`). Adding a field
(as weather once required) means touching every converter or the
frontier/PDF/GUI silently fork — the next "unified class" lives here.

**Rules:** `trait-associated-type-vs-generic`,
`trait-dyn-vs-generic` (keep static dispatch),
`api-parse-dont-validate` (typed core, `String` only at
SQLite/CSV/Slint edges — the established pattern).

**Steps.**

1. Merge the two traits into one (`LapRow` with the union of methods),
   keeping static dispatch (`impl Trait` bounds, no `dyn`). Migrate
   `ordered_lap_key`, `clean_frontier_rows`, `simple_best_rows` to it.
2. Unify converters: exactly one constructor per direction
   (DB row → core row, core row → export row), each used by all
   consumers; delete the manual struct literals in `cli/export.rs` and
   `callbacks/bestlaps.rs` in favor of shared `to_export_rows` /
   `to_external_pdf_records`-style helpers.
3. Keep `String` at SQLite/CSV/Slint boundaries (as with `RaceClass`
   and `WeatherType`); the core row uses typed fields where a type
   already exists.
4. Verify: `cargo test --workspace` with special attention to
   `output_golden`, `pdf_render`, `best_laps_round_trip`, and
   `reviews_and_bestlaps_round_trip_through_worker_thread` (they pin
   the sort/projection contract end to end).

**Acceptance.** One projection trait; one constructor per direction;
goldens byte-identical; a new-field addition touches exactly the core
row + the two directional constructors (assert by code review, not by
test).

---

## Phase 7 — Unify ordering and latest-row SQL

**Findings.**
- Ordering in three flavors: canonical `ordered_lap_key`
  (track, class, weather, ms, driver, car) vs PDF bucket sort
  (track, class, time+mine — drops weather/driver/car tiebreaks) vs
  three SQL `ORDER BY`s (case-sensitive vs `LOWER`, with/without
  weather).
- Latest-row `ROW_NUMBER() OVER (PARTITION BY image_file_id ORDER BY
  created_at DESC, id DESC)` copied across `gui_queries.rs` (2×),
  `image_detail.rs`, `image_debug.rs` (2×),
  `repositories/images.rs`; lap-list projections
  (`image_detail.rs:160` vs `image_debug.rs:492`) with drifted column
  lists (`temp_c`/`is_best_lap` present in one, absent in the other);
  `SELECT current_path … WHERE id=?1` in 5+ places (runner ×2,
  worker ×3, discovery_plan).

**Rules:** `perf-iter-over-index` (keep iterator-side sorting),
`api-single-owner` for SQL fragments.

**Steps.**

1. Rule: SQL pre-sorts cheaply (existing indexes), Rust decides order.
   Document this rule on `ordered_lap_key`.
2. Extract shared SQL fragments as `pub(crate) const`s in `forza-db`
   (latest-row CTE, lap-list projection with the union column list,
   current-path lookup). Migrate all copies; keep result mapping
   untouched.
3. Align PDF bucket tiebreaks with the canonical key OR document why
   the PDF deliberately differs (per-bucket display order) with a test
   pinning the difference. Do not silently change PDF output: if
   alignment changes any golden byte, that is a behavior change needing
   a `CHANGELOG.md` entry and maintainer sign-off.
4. Verify: `output_golden`, `pdf_render`, `gui_inventory`,
   `image_detail` round-trip, `doctor_full` green; plus a manual
   `db-doctor` on a real database when a query shape changes.

**Acceptance.** One CTE/projection definition each; PDF tiebreak rule
documented + pinned; goldens byte-identical unless an explicit,
signed-off behavior change.

---

## Phase 8 — Accepted debt to record, not fix now

These are real but deliberately deferred; this phase only records them
so they are not rediscovered. Suggested home: append to the history
record created when Phases 1–7 land (do not create new permanent docs).

1. **`display_outcome` compensation** (`callbacks/review.rs:29`,
   also `responses.rs:105`, `inventory.rs:83,89`, SQL `CASE` in
   `gui_queries.rs:52`): the DB keeps `outcome='pending'` on
   `auto_resolved` rows by design (CHECK-enforced, Python parity); the
   GUI shows lifecycle truth instead. Convert only if the DB ever gains
   a real system-resolved value.
2. **Backoff triple** (`backend.rs:450` vs `:504` identical
   `(200u64 << (n-1).min(4)).min(5_000)` vs distinct `runtime_backoff`
   vs 5ms/100ms poll sleeps) and the force/retry guard literal in 3
   places (GUI coerces silently instead of erroring). Extract on the
   next backoff tuning, not before (`perf-profile-first`).
3. **Filename philosophies** (`pipeline/naming.rs::safe_name`
   filter-and-trim vs `gui/worker.rs:718 sanitize_export_name`
   replace-with-`_` plus `-N` collision loop). Unify when export naming
   next changes behavior.
4. **Heal temp bypass** (`cli/heal.rs:247` writes temps outside the
   domain rule): accepted, already noted in the hardening plan.
5. **Run/attempt/result lifecycle enums** (Phase 4 of the hardening plan
   deliberately scoped to weather): convert only after a real status
   bug.

## Explicitly out of scope (do not expand into)

- `missing_docs` global gate (needs a `value_enum!` macro change).
- DB `CHECK` on `race_class`/weather vocab (migration, not constraint).
- `mockall`/`loom`/`criterion`, `rayon`, SIMD/PGO (no evidence of need).
- Any Python-tree change (frozen legacy).
- GUI visual redesign beyond the dirty-signal change already shipped.

## Implementation status

All seven phases implemented; each landed only with `cargo fmt --check`,
`cargo clippy --workspace --all-targets -- -D warnings`, and `cargo test
--workspace` green plus byte-identical goldens. Two corrections during
implementation: Phase 1 kept `pub mod commands` (main.rs reaches
grandchild items, so the level must stay visible); Phase 3 switched the
round-trip test to `RunFullDoctor` with arrival-only assertion because
the seeded demo graph is basic-doctor-clean by design, never
full-doctor-clean (see `doctor_basic` vs `doctor_full` suites).
