# Unified RaceClass + Rust skill-rules implementation

Status: historical (frozen record - not a behavior contract)
Audience: maintainer, developer, LLM
Date: 2026-09-14
Scope: `RaceClass` unification (commit `e30ff0a`) and the rust-skills
rule-implementation cycle (error context/chains, lints, casts, param
structs, newtype IDs, doctests, proptest) through this record's commit.
Supersedes: nothing (extends `2026-09-10_post_migration_refinement.md`)
Related tests: `cargo test --workspace` green at every commit, goldens
byte-identical throughout.

## Context

Two latent defect classes motivated this cycle: a new race class could
ship with a silent black fallback color (parallel order/color tables with
`_ =>` arms), and swapped row ids (`run_id` vs `image_file_id` vs
`result_id`, all `String`) compiled fine. Premise unchanged from the
09-10 record: dev phase, no DB compat, test databases regenerate.
Validated live on new screenshots (rename path) before sign-off.

## What was done

- **Unified `RaceClass`** (`e30ff0a`): `order()`/`color()`/`is_spec()`/
  `from_csv_cell()` moved onto the enum with exhaustive matches (no
  wildcard); `class_order()`/`class_color()` remain thin `&str` shims for
  DB-string keys. `detect_race_class`/`extract_class_letter` return
  `RaceClass`; division rosters collapsed into one `DIVISIONS` table with a
  disjointness test; `semantic_filename` takes `RaceClass`;
  `BestLapRow/Filter/Options` typed; review `VALID_CLASSES` and the GUI
  class model derive from the enum. A new class is now a compile error,
  not a silent fallback.
- **Error context + chains:** `encode`/`model load`/DB-path context at the
  `String` boundaries; `anyhow .context()` in CLI open paths;
  `DbError::Transaction` (message-complete) split from source-preserving
  `Pool(r2d2::Error)`; `EncodeError::Io/Image` and
  `LlmError::Transport(reqwest::Error)` keep their sources; `# Errors`
  sections on the key fallible APIs. Display strings unchanged.
- **Build policy:** `[profile.release]` (lto fat, codegen-units 1, strip),
  `rust-version = "1.88"`, `[workspace.dependencies]` with all 9 crates on
  `dep.workspace = true`.
- **Lints:** `correctness = deny`, `suspicious/style/complexity/perf =
  warn` (zero new warnings), `pipeline` onto `lints.workspace = true`.
  `missing_docs` deliberately off (113 warnings in `forza-domain` alone;
  macro-generated variants would need a macro change).
- **Casts:** INI-boundary `i64→u32/u64` saturate (`sat_u32/sat_u64`,
  `try_from().unwrap_or(MAX)`); widenings use `i64::from`; PDF casts
  audited (widening/guarded/latin-1-by-construction).
- **Param structs:** `RequestFingerprint`, `TableBlock`; 4 dead
  `too_many_arguments` allows removed (14 → 6, rest justified).
- **Newtype IDs:** `db/src/ids.rs` (`RunId`, `ImageFileId`,
  `ExtractionResultId`, `AttemptId`, `RunInputId` with
  `Display/AsRef/ToSql/FromSql`); the attempt/result path is typed end to
  end including `WorkerImage` and the runner stages.
- **Docs/tests:** 3 doctests, `proptest` lap-time round-trip,
  `#[must_use]` on pure fns, `Review` detail `format!` without
  intermediate clones.

## Validation performed

- `cargo fmt --all --check`, `cargo clippy --workspace --all-targets --
  -D warnings`, `cargo test --workspace` green at every commit (new:
  `ids_round_trip_through_sqlite`, `division_rosters_are_disjoint`,
  `lap_time_format_parse_round_trip`, class round-trip/garbage tests,
  3 doctests).
- `domain_golden` / `output_golden` / `pdf_render` byte-identical: no
  behavior change, only structure.
- Live screenshot run + rename verified by maintainer before sign-off.

## Deliberately deferred

- `missing_docs` global gate (macro change required).
- DB `CHECK` on `race_class` vocab (`DEFAULT ''` + nullable columns make a
  strict check a migration, not a constraint).
- `mockall`/`loom`/`criterion`, `rayon`, SIMD/PGO (no evidence of need).
