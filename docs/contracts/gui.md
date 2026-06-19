# GUI Contract

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: GUI architecture, state ownership, threading, navigation, and usability
Last verified: 2026-06-17
Supersedes: GUI rules scattered across developer guide and workflow notes
Related tests: `tests/test_gui_*`

The desktop GUI is the primary product surface. It must present current database
state clearly and keep long-running work off the UI thread.

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
- Image Debug / Developer Tools owns raw diagnostic evidence, including any
  future display of internal image flags.

## Layer Rules

- Views emit user-intent signals only.
- Controllers coordinate state, readers, writers, and workers.
- Long-running I/O, database scans, LM Studio calls, and file copying run in
  workers or application/lab services invoked by workers.
- Controllers that own workers implement `close()` and stop threads on
  application shutdown.
- GUI readers are read-only. GUI writers perform explicit mutations and emit
  events so controllers can refresh affected views.
- GUI screens and controllers must use the established GUI facade layer for
  database reads. A visible-scope refresh policy does not justify adding a
  screen-specific SQL service that bypasses `GuiReadService` or another existing
  application/lab facade.
- Best Laps display reads must use the GUI read facade, not the generic
  `ExportLap`/PDF-CSV export path.
- database fixer surface is a controlled application-service surface for named database
  fixers. It must not become a generic SQLite table editor.

## Visible-Scope Refresh Contract

The GUI must update the smallest scope that is currently useful to the user. A
navigation event, tab activation, row selection, detail-tab activation, completed
user action, configuration change, or pipeline event must not automatically cause
unrelated hidden panes to reload heavy state.

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

1. section, such as Process, Review, Images, Best Laps, Records, or Developer
   Tools;
2. tab inside a section, such as Developer Tools Overview, Image Debug, DB
   Doctor, database fixer surface, or Logs;
3. list/detail selection, such as an extraction result row in Image Debug;
4. detail subtab, such as Metadata, Response, Raw model JSON, Extracted data, or
   Error.

A hidden scope should be marked `refresh_pending` instead of refreshed. It should
refresh when it becomes visible, when a user explicitly requests refresh, or when
an authoritative event requires immediate update.

### Event policy

- During an active run, non-visible sections must not reload on per-image events
  such as `image_started`, `image_finished`, attempt events, or intermediate
  review/flag events.
- Visible sections may update during a run, but frequent events should be
  debounced or coalesced where the refresh is expensive.
- `run_finished`, rebuild completion, configuration changes, and explicit user
  refresh actions are authoritative refresh triggers.
- Explicit Refresh buttons bypass staleness and execute immediately.
- User actions that mutate visible data, such as image rename/hide/missing state
  or Review decisions, must update the visible workflow immediately and mark
  affected hidden workflows `refresh_pending`.

### List/detail policy

Entry into a screen loads only the top-level list or summary needed for that
screen. It must not pre-load detail payloads for unselected rows.

Selection loads only the currently visible detail scope. Detail subtab switches
load only the newly visible subtab, reusing cached data when valid.

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
  selected case detail panel.

For Image Debug specifically:

- entering Developer Tools > Image Debug loads the extraction-results list;
- list refresh must not load the first result detail automatically;
- selecting an extraction result loads only the active detail subtab;
- switching among Metadata, Response, Raw model JSON, Extracted data, and Error
  loads only the selected subtab;
- opening Image Debug from Image Details may select the target extraction result,
  but it must still follow the same visible-subtab loading rule;
- scoped reads still go through `GuiReadService`; the controller/view may cache
  and display only the active subtab, but they must not introduce a parallel
  database access layer for Image Debug.

### Best Laps policy

- Opening Best Laps loads the current best-lap table through the GUI read facade
  and then applies filters in memory until a relevant event or explicit reload.
- Best Laps filters define the visible output set. `Generate PDF` and
  `Export CSV` must use the currently filtered rows, not the unfiltered database
  frontier.
- External spreadsheet import belongs to Best Laps because it feeds the final
  table/output workflow. Records may summarize imported data but must not own the
  import action.
- External import may mutate reference data by adding newly observed car names to
  `reference_cars`; the import result must report canonicalized cars, new cars,
  ambiguous cars, unmapped tracks, and invalid laps in the Best Laps page.
- Rebuild recomputes relational derived state only. It must not automatically
  import external spreadsheets or generate a PDF.
- Best Laps may show a top summary/action surface and an image-detail action
  for selected screenshot rows, but it must not duplicate the same table summary
  in a lower text panel.

### Expensive-state policy

The following operations are considered expensive and must not run just because a
hidden section exists:

- full DB Doctor file/hash audit;
- LM Studio HTTP model/runtime probes;
- large raw-response or JSON payload reads;
- large logs or artifact reads;
- bulk table refreshes for Records, Best Laps, Images, or Debug views during a
  run when the section is hidden.

Developer Tools Overview may use fast relational/database checks on entry, but it
must label those checks as fast checks and must not present them as a full DB
Doctor audit. Full DB Doctor runs only from an explicit DB Doctor action.

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
  Developer Tools Overview and Records may expose explicit
  refresh actions because they summarize database files, external spreadsheets,
  LM Studio, or other programs that can change outside the current GUI event
  stream. Logs are internal read-only evidence files and must load on
  entry/configuration/events rather than exposing a manual reload button.
- Action results that affect the user's next decision, such as external import
  summaries or maintenance cleanup results, must be shown inside the active
  workflow, not only in a transient status bar message.

## State Rules

GUI startup must avoid opening expensive database-backed services for screens
that have not been visited. Heavy pages and heavy service reads should initialize
on first page entry or first refresh, not in `MainWindow` startup.

## Raw image flags are not a GUI product surface

`image_flags` rows are internal relational evidence for duplicate/review lifecycle checks. The normal GUI must not expose a generic flags tab, raw flag list, manual flag editor, or direct raw flag status actions.

The Images screen may expose product-level inventory filters only. The duplicate-groups filter is backed by the `image_files.duplicate_of_image_file_id` relationship; duplicate flags remain lifecycle evidence and DB Doctor material, not the inventory authority.

The Review queue owns human correction and dismissal of model/domain issues. A future Developer Tools debug surface may show read-only internal flag evidence only after a dedicated contract is added; it is not part of the current GUI contract.
