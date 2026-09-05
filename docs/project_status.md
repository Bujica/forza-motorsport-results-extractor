# Project Status

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: current product state after the Rust migration (0.21.0-beta.1 was the
final Python baseline; the Rust workspace in `forza-rust/` is current)
Last verified: 2026-09-04
Supersedes: scattered stage notes in implementation and history documents
Related tests: `cargo test --workspace`, `cargo clippy --workspace --all-targets -- -D warnings`, `forza.exe maintenance db-doctor`

This document is the first orientation point for maintenance work. It states the
current released product posture and links to the authoritative contracts.

## Current Stage

The current product version is 0.21.0-beta.1. That was the final stable
baseline of the Python line (`forza/`, now frozen — see
`docs/history/2026-08-25_0.21.0-beta.1_final_python_line_release.md`); the Rust
migration (`docs/plans/2026-08-25_rust_migration_plan.md`) is complete and the
`forza-rust/` workspace (9 crates, Slint GUI + clap CLI over rusqlite) is the
current implementation.
SQLite is the runtime source of truth for extraction runs, inputs, attempts, raw
model evidence, reviews, internal image flags, best laps, Community Records,
performance analytics, and reference catalog data. Legacy runtime JSON caches,
experimental Lab/workbench tooling, compatibility-only repair services,
unsupported image lifecycle states, and non-essential CLI surfaces have been
removed from the product package.

The GUI is the primary operator surface. Images is the normal workflow entry
point: operators synchronize the input folder, review physical-file inventory,
select images, process that selection, then resolve Review/Best Laps outcomes.
Process remains a run/progress surface plus explicit full-folder shortcut. Best
Laps owns PDF/CSV output and external spreadsheet import. Records summarizes
player performance, community-record coverage, car usage/dominance, progress,
filtered rivals, and absolute/relative comparison gaps. Diagnostics provides runtime Overview, image-centric Image Debug, DB Doctor, and Logs. The CLI remains only for essential operational commands: GUI launch,
config check, database upgrade/reset/status, and DB Doctor. LM Studio remains
the runtime model backend.

Raw `image_flags` are retained as SQL infrastructure for duplicate lifecycle,
Review lifecycle, and DB Doctor integrity checks. They are not a normal GUI
read/write surface; product UI paths route through Images inventory state,
duplicate-group relationships, Image Detail Review cases, and the Review queue.

## Current Architecture

| Area | Current document |
| --- | --- |
| Documentation policy | `docs/documentation_policy.md` |
| Database architecture | `docs/architecture/database.md` |
| Architecture overview | `docs/architecture/overview.md` |
| Contracts index | `docs/contracts/README.md` |
| GUI contract | `docs/contracts/gui.md` |
| Developer maintenance | `docs/developer/guide.md` |
| User workflows | `docs/user/guide.md` |
| Advanced GUI tools | `docs/user/advanced_tools.md` |
| Versioning contract | `docs/contracts/versioning.md` |

## Completed Clean-break Work

The 2026-06 SQL/GUI clean-break removed the old development and compatibility
surface while preserving product behavior:

- SQL-first runtime evidence and reference/community-record authority.
- GUI-first operator workflow.
- Essential-only CLI.
- DB Doctor current-schema integrity checks.
- Review, Best Laps, PDF export, Community Records, and reference catalog data.
- Active documentation split into maintainable topic shards.
- Oversized post-cut tests split by product area.
- Removed-surface tests consolidated into compact static guards.

The 0.17.1 patch removed the unused `v_best_laps` view, added Best Laps-focused
read indexes, reduced repeated Best Laps table resize work, and aligned GUI DB
creation with CLI DB upgrade by seeding SQL reference tracks/cars. This keeps
external spreadsheet imports working immediately after DB reset/recreation.

The 0.18.0 release completed the Images-first schema/workflow reset:

- Images is the primary inventory and selection surface.
- Process is run/progress control plus explicit full-folder shortcut.
- Physical image files use current path/name identity and SQL-backed lifecycle
  state.
- Duplicate groups are inventory state and expand after base image filters.
- Review-derived findings remain Review/Image Detail cases; raw flags are
  internal infrastructure.
- Best Laps reads current image identity and uses the simplified participation
  vocabulary.

The 0.19.0 release completed the Performance Records workflow:

- Records/Performance analytics live in an application service and load through
  a GUI worker.
- Records shows track/class/weather records, dry non-TCR community coverage,
  most-used cars, dominant cars, progress, and global rivals.
- Community-record import and filtered PDF/CSV generation remain owned by Best
  Laps.
- Process no longer duplicates output controls, and Best Laps no longer duplicates
  its table summary in a lower text panel.

The 0.20.0 release completed the GUI diagnostics and image workflow polish pass:

- Process uses `Run All` for full-folder execution and reports final total elapsed time.
- Images shows race metadata date in the inventory and Image Details supports previous/next navigation.
- Developer Tools was renamed to Diagnostics, and Records now sits directly below Best Laps.
- Image Debug is image-centric and replaces the former result-centric debug runtime/read/controller/view surface.
- Image Debug exposes screenshot metadata, extraction results, attempts, model response evidence, parsed data, laps/reviews, artifacts, runtime snapshots, and timeline evidence from SQL.

The 0.19.2 stabilization release completed the post-audit hardening pass:

- Encoded image payload metadata now records source image bytes instead of base64 length.
- Community Records imports create active dry snapshots and report rejected rows separately from warnings.
- Review dirty-lap noise is limited to best-lap-impacting dirty laps.
- Records rivals are filtered by the active Records view, and rival/community gaps show absolute and relative values.
- DB Doctor artifact and raw-evidence checks use set-based or batched SQL where possible and avoid unnecessary file hashing when size already differs.
- Image rename rollback validates filesystem postconditions before SQL mutation and verifies rollback cleanup.

Completed implementation plans are archived in:

```text
docs/history/2026-08-25_0.21.0-beta.1_final_python_line_release.md
```

Pre-beta history records (clean-break plans, audits, and release records from
the private development phase) were not published with the public repository.
`docs/history/README.md` explains the boundary.

## Post-0.20.0 Beta Hardening

The following bugs were identified and fixed during public beta validation after
the 0.20.0 release. No schema changes were required. All of this work is part
of the 0.21.0-beta.1 release; see `CHANGELOG.md` for the complete list.

### Stale gamertag in GUI Review write path

**Symptom:** After a Review session (correcting driver names or confirming dirty
laps), all images switched to `non_contributing` and the Best Laps list emptied.
Running CLI `rebuild` restored the frontier.

**Root cause:** `GuiWriteService` captured `user.gamertag` as a frozen string at
construction time. If the GUI config state was reloaded in the background before
the write service was rebuilt (e.g. on a background refresh that did not change
the database path), the frozen gamertag could diverge from the current config
value. A mismatched gamertag causes `FrontierCalculator.clean_frontier_rows` to
find zero player rows and mark every image `non_contributing`.

**Fix:** `GuiWriteService` now accepts the gamertag as a zero-argument callable
(live provider). Review and write controllers pass a lambda closed over
`self._cfg` so every recompute reads the current config value. The
`mark_best_laps` call in `LapRepository` now emits a `DEBUG` log line that
records the effective gamertag and winner count, making future regressions
immediately visible in `forza_debug.log` without forensic analysis.

**Files changed:** `forza/application/gui_write_service.py`,
`forza/gui/controllers/review_controller.py`,
`forza/db/repositories/laps.py`.

### `auto_resolved` review cases invisible in filter views

**Symptom:** After a Rebuild following a Review session, `driver_name` cases
disappeared from both the Open and Resolved filter views. They were only visible
when the filter was set to All.

**Root cause:** The Review filter matched `case.status == "resolved"` exactly.
The Rebuild path sets cases whose triggering condition no longer exists to
`auto_resolved` rather than `resolved`. `auto_resolved` is a system-set terminal
state equivalent to resolved from the operator's perspective, but the literal
string comparison silently excluded it from the Resolved bucket.

**Fix:** `ReviewController._case_matches` now maps any status in
`_RESOLVED_STATUSES = frozenset({"resolved", "auto_resolved"})` to the
`"resolved"` filter bucket before comparison. `auto_resolved` cases now appear
under the Resolved filter tab.

**Files changed:** `forza/gui/controllers/review_controller.py`.

### Gamertag change in Settings did not update Best Laps

**Symptom:** Changing `user.gamertag` in Settings and saving had no visible
effect on the Best Laps list. The frontier remained computed for the previous
gamertag until a new screenshot was processed or CLI `rebuild` was run manually.

**Root cause:** `BestLapsController.on_config_changed` re-applied in-memory
filters when the gamertag changed but did not trigger a database recompute. The
persisted `is_best_lap` flags remained stale, so any subsequent `reload()` would
read the old frontier. Additionally, `SettingsController` and
`BestLapsController` had no write path, so neither could initiate a recompute
without violating their read-only and single-responsibility contracts (which are
enforced by static tests).

**Fix:** Three-part orchestration respecting all architectural constraints:

1. `SettingsController` emits `best_laps_recompute_needed` after a successful
   save that includes `user.gamertag`. The controller remains write-free.
2. `MainWindow` connects this signal to `_on_best_laps_recompute_needed`, which
   calls `GuiWriteService.recompute_best_laps()` (a new public method) and then
   `BestLapsController.reload()` if the section is loaded.
3. `BestLapsController` remains read-only. Its `on_config_changed` continues to
   update the in-memory `_gamertag` value for the "Only Mine" filter; the actual
   DB recompute and cache reload are driven by `MainWindow`.

**Files changed:** `forza/application/gui_write_service.py`,
`forza/gui/controllers/settings_controller.py`,
`forza/gui/main_window.py`.

### Additional 0.21.0-beta.1 hardening

Beyond the three beta-validation fixes above, the release consolidates the
July/August hardening work: QThread workers for DB Doctor/image refresh/Review
reload, screen-aware GUI sizing with mixed table column resize modes,
LM Studio load-config compatibility (ignore `physical_batch_size`, accept
larger `context_length`), cooperative cancellation through backend backoff,
exclusive-access `db-reset`, the `forza/application/image` package split,
immutable run history with latest-result frontier selection, review
`updated_at` stamps, and tightened dirty-lap prompt detection.

## Next Approved Work

The Python line is feature-frozen at 0.21.0-beta.1. The approved next phase is
the Rust migration experiment defined in
`docs/plans/2026-08-25_rust_migration_plan.md`; it starts
with Phase 0 (baseline and contracts) against this release. New Python work is
limited to regression fixes required to keep this baseline healthy.

## Known Issues

- No release-blocking issues are known after the 0.20.0 validation gates and
  post-release bugfixes above.

## Validation Gates

Use these gates when a change affects runtime contracts:

```bash
python -m compileall -q forza
pytest
python -m forza maintenance db-doctor --json
python -m forza --help
python -m forza gui
```

GUI changes also require a manual launch and workflow-specific checks from the
relevant contract document.
