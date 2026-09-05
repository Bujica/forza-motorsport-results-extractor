# GUI

Status: current
Audience: developer, maintainer, LLM
Scope: `forza-gui` — Slint pages, callbacks, worker channel, state rules.

## Pages (`forza-gui/ui/pages/*.slint`, wired in `ui/main.slint`)

images (inventory + detail) · process (run controls, progress, log) · review
(queue + details) · best-laps (frontier + export/import) · diagnostics
(overview, image-debug, doctor, logs) · settings. There is **no Records page**
(frontier/export/import live under Best Laps).

## Event model (no Qt signals — Slint callbacks + typed channel)

- Slint `callback`s declared in `ui/main.slint` (e.g.
  `start-run(bool,bool,bool,bool)`, `cancel-run`, `review-apply/ignore/
  reopen/selected`, `setting-edited`, `debug-result-selected`,
  `open-repository-requested`), handled in `src/lib.rs`.
- Background work goes through `src/worker.rs`: `Request` enum → one
  short-lived job thread each → `Response` enum marshaled back via
  `slint::invoke_from_event_loop`. A panicking job yields
  `Response::Error`; coalescing flags (`*_IN_FLIGHT`) always reset on a
  delivered response so the UI can't wedge on "loading…".
- Live runs use `spawn_extraction` + `RunEvent`s (progress/log/finished),
  not the request channel.

## State rules (`src/lib.rs`, `src/ui_state.rs`)

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
