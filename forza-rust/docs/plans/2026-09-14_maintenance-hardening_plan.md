# Maintenance-hardening implementation plan

Status: planned
Audience: maintainer, developer, LLM
Lifecycle: permanent (until completed, then moved to `../history/`)
Scope: eliminating parallel sources of truth found in the 2026-09-14
architecture audit (dirty symbol, request hash, temperature conversion,
vocabulary enums, SHA-256 helpers, config keys).
Last verified: 2026-09-14
Supersedes: nothing
Related tests: `cargo test --workspace` must stay green; goldens
(`domain_golden`, `output_golden`, `pdf_render`, `response_golden`)
must remain byte-identical unless the plan explicitly says otherwise.

> Project language rule: all project files (code, docs, comments, commit
> messages) are written in English. This plan follows that rule.

## Working agreements (apply to every phase)

1. Behavior preservation first: each phase lands with goldens
   byte-identical unless the phase states a behavior change and updates
   the contract doc in the same change (per `documentation_policy.md`).
2. Gate per phase, before moving on:
   `cargo fmt --all --check`,
   `cargo clippy --workspace --all-targets -- -D warnings`,
   `cargo test --workspace`.
3. One phase per commit; commit message names the phase
   (e.g. `Harden dirty-symbol handling (plan phase 1)`).
4. Update the topic doc in the same change when behavior or workflow
   changes (`reviews.md`, `database.md`, `development.md`,
   `architecture.md`); add `CHANGELOG.md` Unreleased entries for
   user- or maintenance-visible changes.
5. When this plan is fully implemented, move it to `../history/` as a
   dated record and list it in `../history/README.md`.

## Execution order

Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6.
Phases 1–3 remove data divergence (highest risk); 4–6 remove
edit-synchronization burden. Phases are independent in code but ordered
by risk; any phase may be deferred explicitly in the history record.

---

## Phase 1 — Single dirty-symbol definition

**Problem.** Three independent definitions of "dirty mark": the
`DIRTY_TRAILING` regex in `forza-domain/src/lap.rs` (`[▲⚠!△†]`, used by
`is_dirty_lap` / `strip_dirty_symbol` / `parse_lap_time_ms`), the
configured `dirty_lap_symbol` in `forza-config/src/lib.rs` (default `†`,
used only for PDF rendering), and a hardcoded `LIKE '%†%'` in
`forza-db/src/doctor/images.rs`. Configuring another symbol diverges
parsing, rendering, and doctor detection with no error.

**Rules:** `type-no-stringly`, `api-parse-dont-validate`,
`pat-exhaustive-enum`, `test-snapshot-testing` (golden already exists).

**Steps.**

1. Add a single owner for the symbol set, e.g. in `forza-domain/src/lap.rs`:
   - `pub const DEFAULT_DIRTY_SYMBOLS: &str = "▲⚠!△†";` (documents the
     Python-parity set).
   - Build `DIRTY_TRAILING` from that const instead of a literal
     (regex alternation over the const chars).
   - Add `pub fn contains_dirty_symbol(value: &str) -> bool` if the
     doctor needs more than the SQL path (see step 3).
2. Thread the configured symbol: `is_dirty_lap` /
   `strip_dirty_symbol` keep the default set (parse path, Python parity),
   and document on each function that the *render* symbol is
   `cfg.pdf.dirty_lap_symbol` (already separate by design — make the
   separation explicit in docs, not implicit).
3. Parameterize the doctor query in `forza-db/src/doctor/images.rs`:
   replace `LIKE '%†%'` with a `LIKE` pattern built from the same const
   (escape `%`/`_` in symbols). No new behavior for the default set.
4. Tests (all must pass, goldens unchanged):
   - Extend `dagger_is_a_dirty_symbol_like_config_default`-style coverage:
     every char in `DEFAULT_DIRTY_SYMBOLS` is stripped by
     `strip_dirty_symbol`, detected by `is_dirty_lap`, and matched by the
     doctor query helper (extract the `LIKE` builder as a pure,
     unit-testable fn).
   - Add a test asserting the config default (`\u{2020}`) is a member of
     the parse set, so a future default change fails loudly instead of
     silently diverging.

**Acceptance.** `rg '†' crates --type rust` shows only the const
definition, its tests, and the PDF WinAnsi mapping; goldens unchanged;
`reviews.md` dirty-symbol paragraph updated if wording changes.

**Risks.** The PDF `'\u{2020}' => 0x86` WinAnsi slot mapping must stay in
sync with whatever the render symbol is — keep that mapping next to the
const with a comment, do not generalize it.

---

## Phase 2 — One canonical request hash

**Problem.** Two hand-rolled canonical-JSON hashes with overlapping but
different field sets and null semantics:
`forza-lmstudio/src/backend.rs::request_hash` (several fields fixed to
null, `image_bytes` from b64 length) and
`forza-db/src/evidence.rs::canonical_request_hash` (all fields from the
DB row via `RequestFingerprint`). The runner computes the backend hash
6× per extraction and unconditionally overwrites it with the canonical
one before persistence (`insert.request_hash = Some(...)`), so the
backend implementation is dead computation plus drift surface. Doctor
and heal recompute with the canonical one.

**Rules:** `api-single-owner` (single owner per behavior),
`anti-over-abstraction` (do not build a generic hash framework),
`perf-profile-first` (no perf claim; this is dead-code removal).

**Steps.**

1. Confirm deadness once more at implementation time: `rg
   "record\.request_hash" crates` must show only the overwrite site and
   replay/test plumbing. If any live reader of the backend-computed hash
   appears, stop and re-scope (the hash becomes shared instead of
   deleted).
2. Delete `backend::request_hash` and its 6 call sites; leave
   `ModelAttemptRecord.request_hash` unset (`None`) on the live path —
   persistence stamps the canonical value as today.
3. If replay fixtures or tests depend on a backend-shaped hash, keep one
   documented test vector through `canonical_request_hash` (the golden
   in `evidence.rs` already covers this).
4. Update `lm-studio.md` if it describes the backend hash (check at
   implementation time).

**Acceptance.** No `fn request_hash` outside `evidence.rs`; `cargo test
--workspace` green; `response_golden` unchanged; a `rg request_hash`
review shows exactly one implementation plus its 5 known call sites
(runner persist, heal backfill, doctor check, 2 tests).

---

## Phase 3 — One temperature conversion with one default window

**Problem.** `temp_c` is produced two ways:
`db/repositories/laps.rs::insert_lap_record` computes
`ROUND((?11 - 32.0) * 5.0 / 9.0, 1)` inline in SQL with **no**
plausibility window, while the sibling path calls
`forza_domain::lap::fahrenheit_to_celsius` **with** a window (out of
window → NULL). The default window `40/140` is spelled four times:
`forza-config` defaults, `extraction_replay.rs`
`unwrap_or((40.0, 140.0))`, hardcoded args in `laps.rs`, and the heal
fallback on config-load failure.

**Rules:** `api-single-owner`, `const-block`/`const-fn` (single const),
`num-saturating-clamp` (window semantics preserved).

**Steps.**

1. Add `pub const DEFAULT_TEMP_RANGE_F: (f64, f64) = (40.0, 140.0);`
   in `forza-domain/src/lap.rs` (next to `fahrenheit_to_celsius`) with a
   doc comment stating it mirrors the `[validation]` config defaults.
2. Replace the three hardcoded `(40.0, 140.0)` sites
   (`extraction_replay.rs`, `laps.rs`, `heal.rs` fallback) with the
   const. Config-file values still override it; the const is only the
   no-config fallback.
3. Unify the conversion: compute `temp_c` in Rust via
   `fahrenheit_to_celsius` on **both** lap-insert paths and bind the
   result (`Option<f64>` → NULL) instead of the SQL expression. If the
   SQL expression must stay for a documented reason (e.g. bulk path
   without Rust round-trip), add a test pinning formula equivalence
   (`ROUND((x-32)*5/9,1)` vs `fahrenheit_to_celsius` inside the window)
   and document the divergence + which path owns which rows.
4. Tests: extend the existing temperature tests (`heal_nulls_only...`,
   `out_of_window_temperature_persists_null_like_python`) with a case
   asserting both insert paths agree inside and outside the window.

**Acceptance.** `rg "40\.0, 140\.0" crates` shows only the const
definition and config defaults wiring; both insert paths produce
identical `temp_c` for the same input; goldens unchanged.

---

## Phase 4 — Typed vocabulary enums in use (weather first)

**Problem.** `domain/enums.rs` defines `WeatherType`,
`ExtractionStatus`, `RunStatus`, `ImageFileStatus`, `BestLapStatus`,
`ReviewOutcome/Reason/Trigger`, `ReviewDecisionField`,
`ImageFlagType`, `ImageProcessingStatus`, but only one production use
exists (`flags.rs`). Status literals (`"ok"`, `"running"`, …) appear in
~12 files, weather literals plus `eq_ignore_ascii_case("unknown")`
checks in ~10 files, filter literals (`"all"`, `"clean"`, `"dirty"`,
`"screenshots"`, `"external"`) in ~12 files (42 hits in `best_laps.rs`
alone). DDL CHECKs and `doctor/status.rs` are further copies. This is
the exact pre-`RaceClass` situation; follow the same playbook
(`RaceClass::from_csv_cell` is the template).

**Rules:** `type-enum-states`, `type-no-stringly`,
`api-parse-dont-validate`, `pat-exhaustive-enum`,
`api-impl-asref`.

**Steps (weather pilot; repeat per vocabulary only on evidence of churn).**

1. Change `normalize_weather() -> &'static str` to return
   `WeatherType`; keep a thin `&str` shim only where SQL/Slint keys
   require it (same pattern as `class_order`/`class_color` shims).
2. Replace `eq_ignore_ascii_case("unknown")` / `"dry"` / `"rain"`
   comparisons at logic sites (`reviews.rs`, `laps.rs` rain-bucket,
   `best_laps.rs` defaults) with `WeatherType` matches; keep `String`
   at DB/CSV/Slint serialization boundaries via `as_str()`.
3. Derive review/doctor vocabulary lists from the enums (as done with
   `RaceClass::COMPETITION_VALUES`); add an exhaustiveness test mirroring
   `every_variant_has_order_and_non_fallback_color`.
4. Do **not** convert run/attempt/result lifecycles in this phase:
   bigger blast radius (SQL status predicates everywhere); file a
   follow-up only if a status bug actually occurs.

**Acceptance.** New weather value is a compile error at logic sites, not
a silent fallthrough; `rg '"unknown"'` shows only boundaries/tests;
goldens unchanged; `reviews.md` weather paragraph still accurate.

---

## Phase 5 — One SHA-256 helper

**Problem.** Five spellings of the same primitive:
`pipeline/hashing.rs` file hash, `external_import.rs::file_sha256`,
`doctor/helpers.rs::sha256_hex`/`sha256_file`, inline hasher in
`external_records.rs`, inline hasher in `lmstudio`. Same algorithm,
slightly different hex/file conventions.

**Rules:** `api-single-owner`, `perf-io-buffering` (buffered file reads
in the shared helper).

**Steps.**

1. Add `pub fn hash_bytes_hex(bytes: &[u8]) -> String` and
   `pub fn hash_file(path: &Path) -> io::Result<String>` (buffered
   `BufReader`, 64 KiB chunks) to a leaf crate (`forza-pipeline`
   next to `file_hash`, or `forza-domain` if a no-I/O split is wanted —
   decide at implementation time; `hash_file` needs `std::fs` so
   pipeline is the natural home).
2. Reimplement `file_hash`, `file_sha256`, `sha256_hex`, `sha256_file`,
   and both inline hashers as one-line delegates. Keep all existing
   names/signatures (no caller churn beyond the body).
3. Keep exactly one golden test for hex output; delete duplicated
   hash-behavior tests, keeping the highest-value one per call site
   (e.g. `hash_failure_is_recorded...` stays).

**Acceptance.** `rg "Sha256::(new|digest)"` shows only the shared
helper; all hash tests green; no behavior change.

---

## Phase 6 — Centralized config keys

**Problem.** Dotted keys (`"llm.workers"`, `"validation.temp_min_f"`,
`"pdf.dirty_lap_symbol"`, …) are spelled independently in
`forza-config/src/lib.rs` (load), `forza-config/src/save.rs` (write),
and `forza-app/src/services/settings.rs` (74 hits, display). A typo
becomes silent unknown/ignored instead of an error.

**Rules:** `const-block`, `type-no-stringly` (keys as consts, not
literals).

**Steps.**

1. Add `pub mod keys` (or associated consts) in `forza-config`
   exposing every dotted key once, e.g. `pub const WORKERS: &str =
   "llm.workers";`, grouped by section with doc comments.
2. Migrate `lib.rs`, `save.rs`, and `settings.rs` to the consts
   (mechanical; compiler finds every site).
3. Add a test asserting the settings snapshot covers exactly the known
   key set (row count or key-set equality), so a new setting without
   display wiring fails loudly.

**Acceptance.** `rg '"llm\.|"validation\.|"pdf\.'` shows only the const
definitions; settings round-trip test green; GUI Settings page
unchanged.

---

## Explicitly out of scope (do not expand into)

- `missing_docs` global gate (needs a `value_enum!` macro change; see
  `2026-09-14_unified-race-class_and_skill_rules.md`).
- DB `CHECK` on `race_class`/weather vocab (`DEFAULT ''` + nullable
  columns make it a migration, not a constraint).
- `mockall`/`loom`/`criterion`, `rayon`, SIMD/PGO (no evidence of need).
- Run/attempt/result lifecycle enum conversion (Phase 4 covers weather
  only; lifecycles convert only after a real status bug).
- Any Python-tree change (frozen legacy).
