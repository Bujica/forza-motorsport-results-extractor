# Post-migration refinement record (modularization + review + backlog)

Status: historical (frozen record - not a behavior contract)
Audience: maintainer, developer, LLM
Date: 2026-09-10/11
Scope: everything merged after the 2026-09-04 migration sign-off through
commit `0263e88`: god-file splits, discovery/runner dedup, review system
refinement, remaining-backlog phases A-F, and the workers=2 production
incident that motivated configurable inference concurrency.

## Context

Parity with Python was the migration rule; after sign-off it became
reference, not gospel. Premise for this cycle: dev phase, no DB compat,
test databases regenerate from images. Validated live against LM Studio
(`qwen3.6-35b-a3b`) on real screenshots throughout.

## What was done

- **Discovery dedup:** CLI dry-run and the runner shared one
  `build_discovery_plan` (re-hash failures skip loudly everywhere; the
  runner's stale-hash fallback is gone).
- **Runner stages:** `fail_result` (single owner for all `status='error'`
  writes, always logs `error_type: message`), `finalize_ok_stage`
  (finalize + request-image columns + semantic stamp — the missed-stamping
  class is structurally impossible), `build_result_stats`. Two sequential
  sites changed from abort-on-mark-failure (`?`) to `let _`, matching the
  other nine.
- **Splits:** `doctor.rs` (2234 lines) → `doctor/` (10 modules);
  `gui/lib.rs` (2799 lines, 122KB) → `ui_state` thread-locals +
  `handle_response` + `callbacks/` (11 page modules, `lib.rs` ~420 lines);
  `cli/main.rs` (1117) → `commands/` (7 modules, parse + dispatch only).
- **Review refinement:** `ignore case` removed end to end (DDL CHECKs
  shrunk; `ImageFlagStatus` untouched); `decide` classifies
  `confirmed|model_error` with `error_type` taxonomy + `decision:` notes
  (the `model_error_*` doctor checks went from dead to live); reopen
  parity for returning conditions; auto-resolve stamps
  `resolved_at`/`no_longer_detected`; outcome column/filter map the
  lifecycle truth (`display_outcome`, `auto_resolved` filter option).
- **Backlog A-F:** GUI creates the DB from zero (`ensure_database`;
  incompatible refuses with `db-reset` guidance); confirmed-novel cars
  append to shipped `cars.txt` (sorted, best-effort); negative
  selection/sort indexes guarded; single pragma helper; fixed 4-thread GUI
  pool over one r2d2 pool (+ poison recovery + stress test); hot path
  bench-gated (`class_color` match, hoisted lowers; `difflib` sharing
  measured ~0% and reverted).
- **Production incident:** `workers=2` run → 3/5 images failed with LM
  Studio HTTP 500 `failed to process mtmd chunk` (concurrent vision
  calls; SQLite evidence writes held fine — 9 error attempts persisted).
  Fixed by serializing inference; then made configurable:
  `[llm] inference_concurrency` (default 1) via per-run semaphore capped
  at workers. Retry of the 3 images with workers=2: 3/3 ok. Recommendation
  stands: `workers=1` on this hardware; raise both only with servers that
  have parallel slots.

## Validation performed

- `cargo test --workspace`, `cargo clippy --workspace --all-targets`,
  `cargo fmt --all --check` green at every commit (7 new test targets
  added along the way: discovery, decide/outcome, reopen, outcome filter,
  car seed/assets, DB creation, permits, pool stress).
- Live: full 54-image run (54/54 ok), 5+5 runs, workers=2 failure + retry
  recovery, 85-review session decided end to end in the GUI, doctor `OK`
  throughout. `db-doctor` and `config-check` exercised on release builds.

## Deliberately not done

- N+1 query rewrites, PDF `FlateDecode`, tracks.txt sync, `UiState` single
  struct (worsens borrowck), generic parent-mismatch helper, Python-side
  changes (frozen), ordering-semantics changes, DDL shrink beyond review
  vocabs.
