# Best Laps Contract

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: internal best-lap frontier and image-file best-lap participation status
Last verified: 2026-06-21
Supersedes: best-lap notes embedded in developer guide and history
Related tests: `tests/test_db_lap_repository.py`, `tests/test_gui_best_laps_static.py`, `tests/test_gui_write_dirty_decisions.py`

Best-lap state is persisted derived state. Screens read it, but read-only
screens must not silently recompute or mutate it.

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

Best-lap recomputation is explicit. It happens through run finalization,
rebuild, or a dedicated recompute action. The recompute flow updates
`lap_records.is_best_lap` and `image_files.best_lap_status` together.

Review decisions that affect frontier membership or grouping must recompute the
frontier in the normal GUI Review write path. This includes corrections to
`dirty`, `gamertag`, `car`, `track`, `weather`, and `race_class`. The GUI Review
path must not silently leave clean available images as `pending`; if a future
workflow cannot recompute immediately, it must expose an explicit pending
recompute state instead of presenting stale status as complete.

## Gamertag Recompute Contract

The configured gamertag is the primary identity key for the frontier algorithm.
Every row in `lap_records` is classified as contributing or non-contributing
relative to the player identified by `user.gamertag`. A gamertag mismatch
causes the frontier calculator to find zero player rows, producing zero winners
and setting every image to `non_contributing`.

The following invariants must hold at all times:

- The gamertag used at recompute time must match the value in the current
  `forza_config.ini` on disk.
- Write services must not capture the gamertag as a frozen string at
  construction time. They must resolve it via a live provider callable that
  reads from the current config object so background config reloads cannot
  silently introduce a stale value.
- Changing `user.gamertag` in Settings must trigger a best-lap recompute
  before any downstream read of `is_best_lap` or `best_lap_status`. The
  recompute must complete and commit before the Best Laps view refreshes its
  cache.

### GUI gamertag-change flow

`SettingsController` emits `best_laps_recompute_needed` after a successful
save that includes `user.gamertag`. `MainWindow` owns the `GuiWriteService`
used for this recompute and handles the signal:

1. `GuiWriteService.recompute_best_laps()` runs and commits the updated frontier.
2. `BestLapsController.reload()` re-reads the updated rows from SQLite.

`BestLapsController` must remain read-only. It must not own a write service or
trigger the recompute directly. The recompute ownership belongs to the write
layer; the notification path is the `best_laps_recompute_needed` signal.
