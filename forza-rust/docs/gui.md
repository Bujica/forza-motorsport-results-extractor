# GUI

Status: current
Audience: developer, maintainer, LLM
Scope: `forza-gui` — Slint pages, callbacks, worker channel, state rules.

## Startup

`run()` resolves the DB path (config → cwd/ini/exe candidates, workspace
preference), then `ensure_database()`: missing/empty schema is built from
zero via `upgrade()` (catalog seeded). An incompatible schema opens a native
recovery dialog — migrate in place (backup first, data preserved), back up
and recreate from zero, or quit untouched — instead of exiting with an
invisible error (a bare `Err` goes to stderr only, unseen on a console-less
Windows launch). Recovery confirmations show the backup path. A `database
created` line goes to stderr on first run.

## Pages (`forza-gui/ui/pages/*.slint`, wired in `ui/main.slint`)

images (inventory + detail) · process (run controls, progress, log) · review
(queue + details) · best-laps (frontier + export/import) · diagnostics
(overview, image-debug, doctor, logs) · settings. There is **no Records page**
(frontier/export/import live under Best Laps).

## Event model (no Qt signals — Slint callbacks + typed channel)

- Slint `callback`s declared in `ui/main.slint` (e.g.
  `start-run(bool,bool,bool,bool)`, `cancel-run`, `review-apply/
  reopen/selected`, `setting-edited`, `debug-result-selected`,
  `open-repository-requested`), wired per page in `src/callbacks/`
  (`inventory`, `review`, `bestlaps`, `maintenance`, `detail`, `settings`,
  `debug`, `logs`, `about`, `run`) with the worker-response dispatcher in
  `src/callbacks/responses.rs`. `src/lib.rs` keeps bootstrap/geometry only.
- Background work goes through `src/worker.rs`: `Request` enum → fixed pool
  of 4 threads sharing the queue (no thread-per-request) → pooled r2d2
  connections via `WorkerContext::conn()` (no connection-per-request) →
  `Response` enum marshaled back via `slint::invoke_from_event_loop`.
  A panicking job yields `Response::Error`; poisoned locks recover via
  `into_inner()` so coalescing flags (`*_IN_FLIGHT`) always reset on a
  delivered response and the UI can't wedge on "loading…".
- Live runs use `spawn_extraction` + `RunEvent`s (progress/log/finished),
  not the request channel.

## State rules (`src/ui_state.rs`)

- All UI-thread locals live in `ui_state` (models, row caches, selection
  anchors, sort/filter state, worker channel): `lib.rs` and `callbacks/`
  never declare their own. `ROW_CACHE` backs inventory selection; review
  queue has its own `REVIEW_CASES_CACHE` - never index one with positions
  from the other. Selection/sort indexes arrive as `i32` and convert via
  `usize::try_from` (negative `-1` returns early, never wraps).

- `ROW_CACHE` backs inventory selection; review queue has its own
  `REVIEW_CASES_CACHE` — never index one with positions from the other.
- `CURRENT_INVENTORY_FILTER` is the last issued filter; background refreshes
  (rescan/delete/rename/run end/gamertag) reuse it instead of defaults.
- Review option models always start with `all`; combo indexes are clamped
  into range after every model swap.
- Image delete removes the DB row first (FK refusal preserves the file);
  export never overwrites (auto `-N` suffix); rename rolls the file back if
  the DB update fails.
- Settings previews carry a monotonic `seq`; stale arrivals are dropped;
  save/discard invalidate in-flight previews.
- Window geometry persists (DPI-aware); off-screen restores are rejected;
  maximized geometry is not saved as position.
- Selection uses strong-blue row tints (`Theme.selection-bg` focused,
  `Theme.row-selected` multi) so selected rows read clearly on light cards.
- Logs tab reads `cfg.log_file` (+ `<stem>_errors` sibling); a missing
  errors file renders "No errors recorded yet.". "Open folder" creates the
  folder first. The duplicate "Open full page" shortcut was removed.

## Debug views

Image detail (metadata/laps/reviews/extractions/attempts tabs) and image
debug (10 tabs incl. preflight runtime snapshot). Result combo tracks the
actually-loaded result via `debug-result-index`.
