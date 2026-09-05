# Best Laps Contract

Implementation: Rust (forza-rust/) — current. Legacy Python (forza/) frozen at 0.21.0-beta.1.
Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: internal best-lap frontier and image-file best-lap participation status
Last verified: 2026-09-05
Supersedes: best-lap notes embedded in developer guide and history
Related tests: unit tests in `forza-rust/crates/forza-domain/src/frontier.rs`

Best-lap state is persisted derived state. Screens read it, but read-only
screens must not silently recompute or mutate it.

## Frontier Algorithm

The frontier is pure domain logic in `forza-domain/src/frontier.rs`:

- `FrontierLap` is the minimal row projection (`id`, `image_file_id`,
  `track`, `race_class`, `weather`, `temp_f`, `driver`, `car`,
  `best_lap_ms`, `dirty`).
- `clean_frontier_rows(rows, gamertag)` computes the player-side frontier per
  `(track, class, car, condition)` with dominance by time then temperature,
  plus opponents faster than the player's overall limit, deduplicated per
  opponent identity. Condition is `weather` or `"unknown"`; temperature is
  rounded to 0.1 °F. Winners return as `FrontierWinner { id, image_file_id }`,
  sorted by id.
- `simple_best_rows(rows)` is the fallback used when no gamertag is set:
  best clean row per `(track, class, driver, car)`.
- Dirty rows are NOT filtered on the player side of `clean_frontier_rows`: a
  dirty player lap sets the overall limit and can win the frontier — which is
  exactly why `dirty_lap` review cases matter for output.

## Canonical State

- `lap_records.best_lap_ms` is the comparison value.
- `lap_records.best_lap` is display text.
- `lap_records.dirty` stores the dirty-lap marker as structured state.
- `lap_records.is_best_lap` marks rows selected for the persisted frontier.
- `image_files.best_lap_status` summarizes whether a physical image file contributes
  to the current frontier.

Valid image best-lap statuses:

```text
pending
contributing
non_contributing
```

There is no `excluded` image best-lap status and no GUI write path for manual
best-lap exclusion. Skipping files belongs to run-input decisions such as
`selection_excluded`; contribution state belongs to frontier recomputation.

## Dirty-Lap Contract

Dirty state is a lap attribute, not by itself an image-management state. A dirty
lap may still be listed and inspected in best-lap workflows. Correcting a dirty
false positive to clean must update the canonical lap state and must not leave
the image in `pending` unless a real frontier recomputation is required and
scheduled by an explicit recompute/rebuild flow.

## Recompute Contract

Best-lap recomputation is explicit and transactional. It happens through run
finalization, rebuild, or a gamertag-change save:

- `forza-db/src/repositories/best_laps.rs::mark_best_laps(conn, gamertag)`
  recomputes the frontier: it clears all `lap_records.is_best_lap` flags,
  restricts candidates to each image's latest run (lexicographic max `run_id`),
  runs `clean_frontier_rows` (or `simple_best_rows` when the gamertag is
  empty), sets the winners, and updates `image_files.best_lap_status`
  (`contributing` / `non_contributing`) for every touched image — all inside
  one `BEGIN IMMEDIATE` / `COMMIT` transaction (`ROLLBACK` on error), so a
  crash can never leave flags half-cleared.
- `forza-app/src/services/rebuild.rs::rebuild(conn, gamertag)` is the manual
  Rebuild path: apply all persisted corrections → `mark_best_laps` →
  refresh review candidates → sync review flags → refresh run counters.
- End-of-run derived refresh lives in
  `forza-app/src/services/extraction_runner.rs`: after `complete_run`, every
  run calls `rebuild()` so best laps, review cases, and system flags are
  recomputed without requiring a manual Rebuild.

Review decisions that affect frontier membership or grouping recompute the
frontier in the normal GUI Review write path: `DecideCase` applies the
correction via `repositories::corrections::apply_manual_correction` and then
runs `rebuild()` before the UI reloads Review, Best Laps, and Images. This
includes corrections to `dirty`, `driver`, `car`, `track`, `weather`, and
`race_class`. The GUI Review path must not silently leave clean available
images as `pending`; if a future workflow cannot recompute immediately, it
must expose an explicit pending recompute state instead of presenting stale
status as complete.

## Export Contract

Export rows come from `repositories::laps::list_clean_flat`:
`is_best_lap = 1` rows joined with their image metadata, ordered by track,
class, driver, and time. The GUI Best Laps page filters those rows in memory
(`forza-app/src/services/best_laps.rs`: `apply_filters`, `filter_options`,
`summary`); CSV export (`forza-output/src/csv.rs::export_csv`) and PDF
rendering (`forza-output/src/pdf.rs::build_pdf_plan_ext` / `render_pdf`) must
use the currently filtered rows, not the unfiltered database frontier.

## Gamertag Recompute Contract

The configured gamertag is the primary identity key for the frontier algorithm.
Every row in `lap_records` is classified as contributing or non-contributing
relative to the player identified by `user.gamertag`. A gamertag mismatch
causes the frontier calculator to find zero player rows, producing zero winners
and setting every image to `non_contributing`.

The following invariants must hold at all times:

- The gamertag used at recompute time must match the value in the current
  `forza_config.ini` on disk.
- Rust code must not capture the gamertag as a frozen string at
  construction time. The approved pattern is the worker's live-config rule:
  read `user.gamertag` from the mutex-guarded `AppConfig` owned by
  `WorkerContext` at request time, so background config reloads cannot
  silently introduce a stale value.
- Changing `user.gamertag` in Settings must trigger a best-lap recompute
  before any downstream read of `is_best_lap` or `best_lap_status`. The
  recompute must complete and commit before the Best Laps view refreshes its
  cache.

### GUI gamertag-change flow

The worker thread owns the live configuration
(`forza-gui/src/worker.rs::WorkerContext.cfg: Mutex<AppConfig>`) and reads
the gamertag fresh for every request (`gamertag()`), so a background config
reload can never silently introduce a stale value — there is no frozen
gamertag string captured at construction time.

Changing `user.gamertag` in Settings sets `SaveOutcome.gamertag_changed`
(`forza-config/src/save.rs`); the worker then runs `rebuild()` with the new
gamertag and reports `gamertag_recomputed` in the `SettingsOutcome`, after
which the UI reloads Best Laps (plus Review and Images) from the recommitted
frontier. The Best Laps view itself stays read-only: it lists via
`Request::ListBestLaps` and filters in memory, and never triggers recomputes
directly.
