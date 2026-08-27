Status: historical
Audience: developer, maintainer, LLM
Lifecycle: temporary (superseded by `migration_report.md` in this directory)
Scope: detailed porting analysis of `forza-rust/crates/forza-domain` crate
Last verified: 2026-08-27
Supersedes: none
Related tests: `forza-rust/crates/forza-domain/tests/domain_golden.rs`

# Detailed porting analysis — forza-domain

## Overview

Pure domain rules and business types. Zero filesystem, network or SQLite access. Fully ported from Python's `forza/domain/` layer.

| File | Lines | Python Source | Status |
|------|-------|--------------|--------|
| `src/lib.rs` | 21 | `forza/domain/__init__.py` | **Ported** |
| `src/enums.rs` | 306 | `forza/schemas/enums.py` | **Ported** |
| `src/lap.rs` | 269 | `forza/domain/lap.py` | **Ported** |
| `src/race_class.rs` | 68 | `forza/domain/race_class.py` | **Ported (+)** |
| `src/text_utils.rs` | 89 | `forza/domain/text_utils.py` | **Ported** |
| `src/difflib.rs` | 156 | Python built-in `difflib` | **Ported** |
| `src/normalizer.rs` | 218 | `forza/domain/normalizer.py` | **Ported** |
| `src/review_rules.rs` | 142 | `forza/domain/review_rules.py` | **Ported** |
| `src/car_names.rs` | 209 | `forza/domain/car_names.py` | **Ported** |
| `src/ordering.rs` | 145 | `forza/domain/ordering.py` | **Ported** |
| `src/reference_data.rs` | 17 | `forza/domain/normalizer.py` | **Ported** |
| `src/frontier.rs` | 380 | `forza/db/repositories/frontier.py` | **Ported** |
| `src/errors.rs` | 29 | Python ValueError patterns | **Ported (+)** |
| `tests/domain_golden.rs` | 313 | `tools/export_domain_golden.py` | **Ported** |

## enums.rs — Persisted enums with explicit string values

Python reference: `forza/schemas/enums.py` — defines all enums using `ValueStrEnum(str, Enum)`.

Status: **Ported**. All 15+ Python enums ported with identical persisted string values.

| Rust Enum | Python Enum | Values Match |
|-----------|-------------|--------------|
| `WeatherType` | `WeatherType` | dry, rain, unknown — exact |
| `ExtractionStatus` | `ExtractionStatus` | ok, error, cancelled — exact |
| `AttemptStatus` | `AttemptStatus` | ok, error, cancelled — exact |
| `RunStatus` | `RunStatus` | pending, running, completed, failed, cancelled — exact |
| `RunMode` | `RunMode` | normal, dry_run — exact |
| `ImageFileStatus` | `ImageFileStatus` | available, missing — exact |
| `BestLapStatus` | `BestLapStatus` | pending, contributing, non_contributing — exact |
| `ImageProcessingStatus` | `ImageProcessingStatus` | unprocessed, processing, processed_ok, processed_error, cancelled, skipped — exact |
| `ImageFlagStatus` | `ImageFlagStatus` | active, resolved, ignored — exact |
| `ImageFlagType` | `ImageFlagType` | duplicate, dirty_lap, track, weather, race_class, car, driver_name — exact |
| `ReviewCaseStatus` | `ReviewCaseStatus` | open, resolved, ignored, auto_resolved — exact |
| `ReviewOutcome` | `ReviewOutcome` | pending, confirmed, model_error, ignored — exact |
| `ReviewReason` | `ReviewReason` | dirty_lap, track, weather, race_class, car, driver_name — exact |
| `ReviewTrigger` | `ReviewTrigger` | all 13 variants match exactly |
| `ReviewDecisionField` | `ReviewDecisionField` | dirty, track, weather, race_class, car, driver — exact |
| `CorrectionCause` | `CorrectionCause` | review, rebuild, auto, unknown — exact |
| `RuntimeSnapshotKind` | `RuntimeSnapshotKind` | preflight — exact |
| `ExportFormat` | `ExportFormat` | csv, pdf — exact |
| `RaceClass` | `RaceClass` | E, D, C, B, A, TCR, S, R, P, X, Mixed, Unknown — exact |

Rust addition: `value_enum!` macro provides `impl FromStr`, `impl Display`, arrays `ALL`/`VALUES`, method `from_value()`.

Test: `persisted_values_match_python_contract` verifies each enum against Python contract.

## lap.rs — Time parsing, dirty detection, sanitization, weather, temperature, class

Python reference: `forza/domain/lap.py` — single module containing all these functions.

Status: **Ported**. All functions ported with identical behavior.

| Rust Function | Python Function | Match Status |
|---------------|-----------------|--------------|
| `strip_dirty_symbol()` | `strip_dirty_symbol()` | Exact logic (variation selectors + trailing symbol regex) |
| `parse_lap_time_ms()` | `parse_lap_time_ms()` | Identical MM:SS.mmm / SS.mmm parsing, placeholder handling, gap-time rejection |
| `format_lap_time_ms()` | `format_lap_time_ms()` | Same divmod-based formatting with optional dirty suffix |
| `is_dirty_lap()` | `is_dirty_lap()` | Same trailing-symbol detection logic |
| `sanitize_driver_name()` | `sanitize_driver_name()` | NFKC normalization, variation selector removal, Unicode category filtering, whitespace collapse |
| `normalize_weather()` | `normalize_weather()` | Identical English/Portuguese mapping to dry/rain/unknown |
| `fahrenheit_to_celsius()` | `fahrenheit_to_celsius()` | Same formula with range validation (added Rust-specific min/max params) |
| `fahrenheit_to_celsius_str()` | *(Rust addition)* | Python handles string internally; Rust splits into typed + str variants |
| `extract_class_letter()` | `extract_class_letter()` | Identical regex-based extraction from "692 A", "692A", bare letters |
| `detect_race_class()` | `detect_race_class()` | Same 30% TCR threshold, multi-letter Mixed detection, single letter fallback |

Differences: Rust uses `regex::Regex` + `LazyLock`; Python uses inline `re.match()`. Rust adds `fraction_ms()` helper and `fahrenheit_to_celsius_str()`.

## race_class.rs — Canonical class ordering and presentation colors

Python reference: `forza/domain/race_class.py` — contains only `CLASS_ORDER` dict (16 lines).

Status: **Ported (+)**. `class_order()` mirrors Python exactly. Rust addition: `CLASS_COLORS` static HashMap with hex codes per class (from PDF/GUI contract).

## text_utils.rs — Text normalization helpers

Python reference: `forza/domain/text_utils.py`.

Status: **Ported**. `normalize_whitespace_lower()`, `normalize_ascii_compare()` identical. `load_nonempty_lines_from_str()` replaces file path variant with string slice (embedded assets). Rust uses crate `unicode_canonical_combining_class`; Python uses `unicodedata.combining()`.

## difflib.rs — Faithful port of SequenceMatcher.ratio + get_close_matches

Python reference: built-in `difflib` module.

Status: **Ported (subset)**. Implements recursive longest-matching-block decomposition identically. Autojunk explicitly disabled (safe for project inputs). Self-contained port, no external dependency.

## normalizer.rs — Reference data + track/car correction strategies

Python reference: `forza/domain/normalizer.py`.

Status: **Ported**. `fix_track_name()` 6-step strategy identical (exact, accent-normalised, punctuation-insensitive, prefix, fuzzy 0.75, unchanged). `fix_car_name()` 4-step strategy identical (exact normalized, substring unique, fuzzy 0.85, unchanged). Rust uses self-contained difflib; Python imports built-in.

## review_rules.rs — Review-case trigger detection and track suggestions

Python reference: `forza/domain/review_rules.py`.

Status: **Ported**. `has_suspicious_name_symbol()`, `has_numeric_name_prefix()`, `driver_name_review_trigger()`, `ambiguous_raw_track()`, `track_suggestions()` all identical. Rust returns `Option<&'static str>` instead of Python heap-allocated strings.

## car_names.rs — Deterministic import canonicalization

Python reference: `forza/domain/car_names.py`.

Status: **Ported**. `car_match_key()`: NFKC normalization, apostrophe unification, year collapse ('74 <-> 1974), non-word removal — exact logic. `car_canonical_map()` returns `(unique_map, collisions)` tuple identical. `canonicalize_car_name()` 5-step resolution identical.

## ordering.rs — Shared ordering keys for best laps

Python reference: `forza/domain/ordering.py`.

Status: **Ported**. `ordered_lap_key()` returns flat 8-tuple instead of Python nested tuples; ordering semantics identical (tuple comparison lexicographic). Rust uses `i64` for ms; Python uses `int` arbitrary precision — functionally equivalent.

## reference_data.rs — Embedded reference catalog

Python reference: `forza/domain/normalizer.py::load_reference_seed_text_data()`.

Status: **Ported**. `include_str!()` compiles assets into binary at compile time instead of filesystem I/O at runtime. Functionally equivalent but zero file reads.

## frontier.rs — Best-lap frontier calculation

Python reference: `forza/db/repositories/frontier.py::FrontierCalculator`.

Status: **Ported**. `simple_best_rows()`: clean-only filtering, sort by time, dedup per (track, class, driver, car) — exact. `clean_frontier_rows()`: full frontier algorithm with dirty-lap semantics preserved exactly — player's dirty lap sets the limit and can win the frontier. Rust uses trait-based generic `<L: FrontierLap>` instead of Python Protocol.

Critical note: dirty-lap frontier logic preserved exactly; dirty lap review cases exist because dirty lap defines the limit and legitimately wins. Correcting dirty does not change the time — corrected lap continues dominating.

## errors.rs — Domain error types

Python reference: Python uses generic `ValueError`.

Status: **Ported (+)**. Rust typed enum via thiserror with `Display` + `std::error::Error`. `DomainError::NonPositiveLapTime`, `UnknownEnumValue { enum_name, value }`.

## tests/domain_golden.rs — Golden equivalence tests against Python

Python reference: `tools/export_domain_golden.py` → `fixtures/expected/domain_golden.json`.

Status: **Ported**. 15 golden tests covering all exported functions. Custom helpers (`optional_str`, `number_or_string_i64`, `f64_or_string`) handle Python encoding `None`/`__NONE__` and mixed number/string types.

## Overall assessment

`forza-domain` is a **complete, faithful port** of the Python domain layer. Every function, type and algorithm ported with identical behavior verified by golden equivalence tests against real Python-generated reference vectors. Rust adds ergonomic improvements (typed enums with FromStr/Display, compile-time asset embedding, trait-based generic interfaces) without altering any domain logic or output values.
