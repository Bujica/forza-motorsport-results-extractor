# GUI Contract

Implementation: Rust (forza-rust/) — current. Legacy Python (forza/) frozen at 0.21.0-beta.1.
Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: GUI architecture, state ownership, threading, navigation, and usability
Last verified: 2026-09-05
Supersedes: GUI rules scattered across developer guide and workflow notes
Related tests: unit tests in `forza-rust/crates/forza-gui` and `forza-app` service tests

The desktop GUI is the primary product surface. It must present current database
state clearly and keep long-running work off the UI thread.

## Architecture

The desktop GUI is a Slint front-end (`forza-gui` crate). The shell and pages
are declared in `forza-gui/ui/` (`main.slint` plus `pages/`, `components/`,
`models.slint`, `theme.slint`); behavior lives in `forza-gui/src/lib.rs`.

Threading contract:

- Slint callbacks are synchronous and only enqueue typed `Request` values
  over an mpsc channel (`forza-gui/src/worker.rs`).
- A dedicated worker thread hosts request handling. Each request runs on its
  own short-lived job thread so a heavy job (e.g. full DB Doctor) never
  blocks a light one (e.g. image detail); a panicking job yields
  `Response::Error` instead of wedging the UI behind "loading…".
- Results return as plain-data `Response` values marshaled to the UI thread
  via `slint::invoke_from_event_loop`. The worker never touches widget types.
- The worker owns the live `AppConfig` plus the INI path
  (`WorkerContext`), so every handler observes the current configuration.
- Live extraction runs on a separate dedicated thread
  (`forza-app/src/services/extraction_runner.rs::spawn_extraction`) with a
  cooperative `RunControl` (cancel / pause) and a `RunEvent` stream
  (`Started`, `Plan`, `ImageStarted`, `ImageDone`, `Progress`, `Log`,
  `Finished`, `Failed`) marshaled to the event loop. When `workers > 1`,
  images are processed in parallel across Tokio tasks.
- Widget-adjacent state (Slint models, row caches, selection, filter state)
  lives in UI-thread locals and is never shared across threads.

See `docs/contracts/gui_signal_payloads.md` for the full callback →
request → response inventory.

## Primary Workflow

The normal operator flow is:

```text
Images -> select files -> Process -> Review / Best Laps
```

Images is the first workflow screen. It represents the configured input folder
and synchronizes supported physical image files into the database through a
background worker so GUI startup is not blocked by filesystem hashing or
metadata inspection. A file may appear in Images while still unprocessed.

Images processing-status projection must be derived from the latest extraction result per image, with skipped run inputs used only as fallback for images without results. It must not load the full extraction-result history for every visible image during a table refresh.

Process remains the run/progress/configuration screen. GUI extraction starts
from Images through the selected image-file ids. Process may also expose an
explicit `Run input folder` command for the whole configured input folder, but
the UI must label that action as a full-folder run, keep selected processing
anchored in Images, and avoid duplicating Best Laps output controls.

## Product Surface Ownership

The normal GUI must keep inventory, review, and debug concepts on separate
surfaces:

- Images owns physical-file inventory, processing status, best-lap
  participation, and inventory indicators such as duplicate groups.
- Review owns human-facing review cases and correction decisions. Images must
  not duplicate Review by exposing review-reason filters such as `dirty_lap`,
  `track`, `weather`, `race_class`, `car`, `gamertag`, or
  `driver_name`.
- Image Details is a normal operator detail surface. It may show metadata,
  laps, linked Review cases, extraction summaries, and attempts, but it must
  not expose raw internal `image_flags` as a normal tab.
- Image Debug / Diagnostics owns raw diagnostic evidence, including any
  future display of internal image flags.

## Layer Rules

- Views emit user-intent callbacks only (declared in `main.slint`).
- `lib.rs` page-callback handlers coordinate state and enqueue worker
  `Request` values; they never touch the database or the filesystem directly
  (except local UI concerns: file-picker dialogs, clipboard, opening URLs).
- Long-running I/O, database scans, LM Studio calls, and file copying run in
  worker job threads, the extraction runner thread, or application services
  invoked by workers.
- Read paths go through the worker's pure `handle_request` plus application
  services (`ImageInventoryService`, `list_review_cases`, `list_best_laps`,
  `load_image_detail`, debug/overview/doctor services). Screens must not add
  a parallel database access layer that bypasses them.
- Best Laps display reads use `Request::ListBestLaps` plus in-memory
  filtering, not the `ExportRow`/CSV export path. CSV/PDF export uses the
  currently filtered rows via `forza_output`.
- Read-only views must not trigger best-lap recomputes. Recomputes caused by
  external events (gamertag change via `SaveSettings` →
  `SettingsOutcome.gamertag_recomputed`, manual `RunRebuild`, run-finalized
  `rebuild()`) are followed by `ListBestLaps` (plus Review/Images) reloads.
- The worker must resolve `user.gamertag` from its live mutex-guarded
  `AppConfig` at request time, never from a frozen string captured at
  construction time. This prevents a stale gamertag from corrupting the
  best-lap frontier when the config is reloaded in the background.

## Visible-Scope Refresh Contract

The GUI must update the smallest scope that is currently useful to the user. A
navigation event, row selection, detail-tab switch, completed user action,
configuration change, or pipeline event must not automatically cause
unrelated hidden views to reload heavy state.

Verified mechanisms in `forza-gui/src/lib.rs` + `worker.rs`:

- Request coalescing: rapid Images filter changes collapse through
  `INVENTORY_REFRESH_IN_FLIGHT` / `PENDING_INVENTORY_FILTER` (same for Review
  via `REVIEW_REFRESH_IN_FLIGHT` / `PENDING_REVIEW_FILTER`); only the latest
  pending filter is issued when the in-flight request completes. A worker
  `Response::Error` resets both flags so the UI can never wedge behind
  "loading…".
- Filter preservation: the last-issued inventory filter is remembered
  (`CURRENT_INVENTORY_FILTER`) so background refreshes (post-decision,
  rescan, delete, rename, rebuild, run finish) reload with the user's active
  filter bar, never forced defaults. The Review reloads reuse the active
  `REVIEW_FILTER`.
- Lazy page entry: startup issues one inventory request plus open-bucket
  Reviews plus Best Laps. Settings, Logs, and Diagnostics payloads load on
  first page entry (`page-changed`); entering Diagnostics also preloads the
  overview snapshot and Image Debug cases. Heavy pages must initialize on
  first entry, not at window startup.
- Settings previews carry a monotonic sequence number; a preview response
  older than the latest edit is dropped instead of restoring stale rows.

Use these terms for GUI refresh state:

- `refresh_pending`
- `stale`
- `stale_section`
- `stale_sections`
- `needs_refresh`

Do not use `dirty`, `dirty_sections`, `mark_dirty`, or `is_dirty` for GUI refresh
state. `dirty` is reserved for the domain concept of dirty laps.

### Scope hierarchy

Refresh decisions are scoped in this order:

1. section, such as Process, Review, Images, Best Laps, or Diagnostics;
2. tab inside a section, such as Diagnostics Overview, Image Debug, DB
   Doctor, or Logs;
3. list/detail selection, such as an extraction result row in Image Debug;
4. detail subtab, such as Metadata, Response, Raw model JSON, Extracted data, or
   Error.

A hidden scope should be marked `refresh_pending` instead of refreshed. It should
refresh when it becomes visible, when a user explicitly requests refresh, or when
an authoritative event requires immediate update.

### Event policy

- During an active run, non-visible views must not reload on per-image events
  (`ImageStarted`, `ImageDone`, `Progress`); the Process page appends run-log
  lines and updates progress in place.
- `Finished` (and `Failed`) are authoritative refresh triggers: the handler
  sends `RefreshOverview`, `RefreshInventory` (current filter),
  `ListBestLaps`, and `ListReviews` (current filter).
- Rebuild completion reloads Reviews (all bucket) and Best Laps.
- Review apply/ignore/reopen reload Reviews and Best Laps, plus Images with
  the current filter (decisions can change best-lap/processing columns).
- Rescan/delete/rename reload Images with the current filter.
- External import reloads Best Laps and surfaces the import summary in the
  status line.
- Explicit user refresh actions (scan folder, refresh buttons, reload)
  bypass coalescing and execute immediately.
- User actions that mutate visible data, such as image rename/export/rescan/
  delete or Review decisions, must update the visible workflow immediately
  via the response handlers above.

### List/detail policy

Entry into a screen loads only the top-level list or summary needed for that
screen. It must not pre-load detail payloads for unselected rows.

Selection loads only the currently selected detail scope via a worker request
(`LoadImageDetail`, `LoadImageDebugDetail`, `LoadPreview`).

For Image Details specifically:

- normal tabs are Metadata, Laps, Review cases, Extractions, and Attempts;
- Review cases are the operator-facing explanation for model or validation
  findings linked to the image;
- internal `image_flags` must not be rendered as a normal detail tab.

For Review specifically:

- entering Review refreshes through the active view filters;
- Review filter changes apply to the controller's cached queue in memory after
  the first DB load;
- Review decisions mutate the cached queue and advance selection without forcing
  a full DB reload;
- the Review case queue must not expose internal `business_key` or source-file
  columns as primary table columns. Those diagnostic values may appear in the
  selected case detail panel;
- Review filters that match on `status` must treat `auto_resolved` as belonging
  to the `resolved` bucket. A filter that shows resolved cases must show
  `auto_resolved` cases; a filter that shows open cases must not show
  `auto_resolved` cases. Matching only on the literal string `"resolved"` and
  silently hiding `auto_resolved` is a bug.

For Image Debug specifically:

- entering Diagnostics preloads the debug case list;
- selecting a case sends `LoadImageDebugDetail` for that image;
- selecting a result reloads the detail with that result selected;
- opening Image Debug from Image Details navigates to Diagnostics and loads
  the target image detail plus the case list;
- scoped reads still go through the worker; the UI may cache and display
  only the active detail scope, but it must not introduce a parallel
  database access layer for Image Debug.

### Best Laps policy

- Opening Best Laps sends `ListBestLaps`; rows are cached (`BESTLAP_ALL`) and
  filters apply in memory until a relevant event or explicit reload.
- Best Laps filters define the visible output set. `Generate PDF` and
  `Export CSV` must use the currently filtered rows, not the unfiltered database
  frontier.
- External spreadsheet import belongs to Best Laps because it feeds the final
  table/output workflow (`bestlaps-import` → `Request::ImportExternalRecords`
  → `import_to_db` → `ListBestLaps` reload with the import summary).
- External import may mutate reference data by adding newly observed car names to
  `reference_cars`; the import result must report canonicalized cars, new cars,
  ambiguous cars, unmapped tracks, and invalid laps in the Best Laps page.
- Rebuild recomputes relational derived state only. It must not automatically
  import external spreadsheets or generate a PDF.
- Best Laps may show a top summary/action surface and an image-detail action
  for selected screenshot rows, but it must not duplicate the same table summary
  in a lower text panel.
- The Best Laps view is read-only. It must not trigger best-lap recomputes
  directly. Recomputes caused by external events (gamertag change, rebuild,
  run finish, Review decisions) are followed by a `ListBestLaps` reload.
- Changing `user.gamertag` in Settings must trigger a best-lap recompute before
  Best Laps refreshes its cache. The approved path is:
  `SaveSettings` → worker `rebuild()` with the new gamertag →
  `SettingsOutcome.gamertag_recomputed` → UI reloads Best Laps (plus Review
  and Images).

### Expensive-state policy

The following operations are considered expensive and must not run just because a
hidden section exists:

- full DB Doctor file/hash audit;
- LM Studio HTTP model/runtime probes;
- large raw-response or JSON payload reads;
- large logs or artifact reads;
- bulk table refreshes for Best Laps, Images, or Debug views during a
  run when the section is hidden.

Diagnostics Overview may use fast relational/database checks on entry, but it
must label those checks as fast checks and must not present them as a full DB
Doctor audit. Full DB Doctor runs only from an explicit DB Doctor action
(`doctor-requested` → `Request::RunFullDoctor`).

## Usability Rules

- Controls must have enough width for their expected text.
- Filter controls, comboboxes, tab labels, and action controls must size to
  their expected text.
- Comboboxes with finite vocabularies must use content-aware sizing or explicit
  minimum widths.
- No filter label/value may be clipped or compressed in the normal 1280px
  desktop layout.
- Review and table workflows must support mouse and keyboard navigation where
  repeated decisions are expected.
- Review lap tables must show the normal maximum result size of 13 drivers
  without requiring vertical scrolling in the normal desktop layout.
- Rare actions must not compete visually with primary review actions.
- A screen must not show stale snapshot values as current canonical values.
- Similar labels should not be repeated in adjacent container titles unless they
  distinguish different scopes.
- Manual refresh buttons should be avoided whenever possible. GUI state should
  refresh on page/tab entry, relevant filter changes, completed user actions,
  configuration changes, and application events. A visible refresh action is an
   exception for external or expensive state that cannot be observed reliably,
   and the reason must be clear from the surrounding workflow. DB Doctor,
   Diagnostics Overview, and Best Laps import may expose explicit
   refresh actions because they summarize database files, external spreadsheets,
  LM Studio, or other programs that can change outside the current GUI event
  stream. Logs are internal read-only evidence files and must load on
  entry/configuration/events rather than exposing a manual reload button.
- Action results that affect the user's next decision, such as external import
  summaries or maintenance cleanup results, must be shown inside the active
  workflow, not only in a transient status bar message.

## State Rules

GUI startup must avoid opening expensive database-backed reads for screens
that have not been visited. Heavy pages and heavy worker reads should initialize
on first page entry or first refresh, not at window startup.

## Raw image flags are not a GUI product surface

`image_flags` rows are internal relational evidence for duplicate/review lifecycle checks. The normal GUI must not expose a generic flags tab, raw flag list, manual flag editor, or direct raw flag status actions.

The Images screen may expose product-level inventory filters only. The duplicate-groups filter is backed by the `image_files.duplicate_of_image_file_id` relationship; duplicate flags remain lifecycle evidence and DB Doctor material, not the inventory authority.

The Review queue owns human correction and dismissal of model/domain issues. A future Diagnostics debug surface may show read-only internal flag evidence only after a dedicated contract is added; it is not part of the current GUI contract.
