# GUI Event Payload Contracts

Implementation: Rust (forza-rust/) — current. Legacy Python (forza/) frozen at 0.21.0-beta.1.
Status: current
Audience: developer, maintainer, LLM
Lifecycle: permanent
Scope: Slint callback + GUI worker channel payload documentation
Last verified: 2026-09-05

There are no PySide6 `Signal(object)` payloads in the Rust GUI. Cross-boundary
communication has two typed layers, both with payloads documented below:

1. Slint callbacks declared in `forza-gui/ui/main.slint` (user intent from
   pages, handled synchronously in `forza-gui/src/lib.rs`).
2. The typed worker channel in `forza-gui/src/worker.rs`: the `Request` enum
   (UI → worker job threads) and the `Response` enum (worker → UI thread via
   `slint::invoke_from_event_loop`).

When adding or changing a callback, `Request`, or `Response` variant, update
this document in the same patch.

## Slint callback inventory

Callbacks are declared as `callback <name>(args...)` on `MainWindow` in
`forza-gui/ui/main.slint` and wired with `main.on_<name>(...)` in
`forza-gui/src/lib.rs`. The "Handler" column names the `Request` enqueued or
the local UI-thread handling.

| Callback (`main.slint`) | Slint signature | Handler (`lib.rs` → `Request` or local) |
| --- | --- | --- |
| `refresh-requested` | `(string, string, string, string, string, string)` | `Request::RefreshInventory { filter }` — `(file_status, best_lap_status, inventory_filter, track, run_id, processing_status)`; `"all"` maps to `None`; coalesced via `PENDING_INVENTORY_FILTER`. |
| `scan-folder` | `()` | `Request::SyncInputFolder { filter }` with the current inventory filter. |
| `selection-changed` | `(int)` | Row index → sets Images detail header locally + `Request::LoadImageDetail { image_id }` from the row cache. |
| `selection-toggle` | `(int)` | Local multi-selection toggle (anchor-based). |
| `selection-single` | `(int)` | Local single selection. |
| `selection-range` | `(int)` | Local Shift+click range from the anchor row. |
| `select-all` | `()` | Local: select all cached rows. |
| `clear-selection` | `()` | Local: clear selection + summary. |
| `export-selected` | `()` | Native folder dialog, then `Request::ExportImages { image_ids, dest_dir }`. |
| `rescan-selected` | `()` | `Request::RescanImages { image_ids }` for the selection. |
| `delete-selected` | `()` | After `confirm-delete`, `Request::DeleteImages { image_ids }`. |
| `sort-changed` | `(int)` | Local: re-sort the cached inventory rows. |
| `process-selected` | `()` | Local: stash selected ids (`RUN_SELECTED_IDS`) and navigate to Process; the next `start-run` consumes them. |
| `rename-selected` | `()` | `Request::RenameImages { image_ids }` for the selection. |
| `reviews-requested` | `()` | `Request::ListReviews { filter }` with the active `REVIEW_FILTER`; coalesced via `PENDING_REVIEW_FILTER`. |
| `review-filter-changed` | `(string, string, string, string)` | `(status, reason, outcome, run)` → updates `REVIEW_FILTER` + `Request::ListReviews`. |
| `review-selected` | `(int)` | Local: render the selected case detail from `REVIEW_CASES_CACHE` (+ `LoadPreview` when the case has an image). |
| `review-apply` | `(int, string, string)` | `(case_number, field, value)` → `Request::DecideCase`; on success reloads Reviews + Best Laps + Images. |
| `review-ignore` | `(int)` | `Request::IgnoreCase { case_number }`. |
| `review-reopen` | `(int)` | `Request::ReopenCase { case_number }` (flag re-sync happens in the worker). |
| `review-open-detail` | `(int)` | Local navigation: open Image Detail by the case's image id (never reuses the review-cache position as an inventory index). |
| `review-preview-requested` | `(string)` | `Request::LoadPreview { image_file_id }`. |
| `bestlaps-requested` | `()` | `Request::ListBestLaps`. |
| `bestlaps-filter-changed` | `(string, string, string, string, string, string, string, bool)` | `(track, class, weather, driver, car, lap, source, only_mine)` → local in-memory `apply_bestlaps_filters`. No worker request. |
| `bestlaps-sort-changed` | `(int)` | Local: toggle/replace `BESTLAP_SORT`, re-apply filters. |
| `bestlaps-export-csv` | `()` | Local: native save dialog, filter cached rows, `forza_output::export_csv`. |
| `bestlaps-generate-pdf` | `()` | Local: filter cached rows, `build_pdf_plan_ext` with `cfg.pdf` options, `render_pdf` to the configured pdf path. |
| `bestlaps-open-pdf` | `()` | Local: open the configured PDF report. |
| `bestlaps-import` | `()` | Native file dialog, then `Request::ImportExternalRecords { path }`. |
| `bestlaps-detail-requested` | `(string)` | `Request::LoadImageDetail { image_id }` for the row's `image_file_id`. |
| `doctor-requested` | `()` | `Request::RunFullDoctor` (full audit; Overview shows fast checks only). |
| `rebuild-requested` | `()` | `Request::RunRebuild` → on completion reloads Reviews (all bucket) + Best Laps. |
| `overview-requested` | `()` | `Request::RefreshOverview`. |
| `start-run` | `(bool, bool, bool, bool)` | `(dry_run, force, retry, debug)` → dry-run plans via `Request::RunDryRun`; otherwise spawns the extraction thread (`spawn_extraction`) unless a run is active. |
| `cancel-run` | `()` | Local: `RunControl::request_cancel()`. |
| `toggle-pause` | `()` | Local: flip `RunControl` paused flag. |
| `open-image-detail` | `(int)` | Inventory row index → `Request::LoadImageDetail { image_id }` (or directly when the image is outside the cached window). |
| `detail-tab-changed` | `(string)` | Local detail tab switch. |
| `detail-prev` / `detail-next` | `()` | Local detail stepping (`step_detail`). |
| `detail-close` | `()` | Local: navigate back to Images. |
| `setting-edited` | `(string, string)` | `(key, value)` → pending map + `Request::PreviewSettings { changes, seq }`; stale seq responses are dropped. |
| `discard-settings` | `()` | Local: clear pending, bump seq, `Request::LoadSettings`. |
| `save-settings` | `()` | `Request::SaveSettings { changes }`; a gamertag change triggers `rebuild()` in the worker. |
| `page-changed` | `(string)` | Local: lazy loads — Settings first entry, Logs, Best Laps, Diagnostics (overview + debug cases). |
| `debug-refresh-requested` | `()` | `Request::ListImageDebugCases` with the default filter. |
| `debug-filter-changed` | `(string, string, string, string, string)` | `(status, backend, model, prompt, run)` → `Request::ListImageDebugCases { filter }`. |
| `debug-case-selected` | `(int)` | Case index → `Request::LoadImageDebugDetail { image_file_id, selected_result_id: None }`. |
| `debug-result-selected` | `(string)` | `Request::LoadImageDebugDetail` with the current image id + selected result id. |
| `open-image-debug` | `(string)` | Navigate to Diagnostics/Debug + `Request::LoadImageDebugDetail` + `Request::ListImageDebugCases`. |
| `debug-open-image-detail` | `()` | Navigate to Image Detail + `Request::LoadImageDetail` for the debug image. |
| `logs-reload-requested` | `()` | `Request::LoadLogs`. |
| `logs-clear-requested` | `(string)` | Native confirm dialog, then `Request::ClearLogs { which }` (`app` or `errors`). |
| `logs-open-folder` | `()` | `Request::OpenLogFolder`. |
| `logs-search-changed` | `(string)` | Local: filter cached log lines. |
| `about-requested` | `()` | Local: fill + show the About overlay (version, config, DB, gamertag, doctor/overview state). |
| `copy-diagnostics-requested` | `()` | Local: copy About text to the clipboard. |
| `open-repository-requested` | `()` | Local: open the GitHub repository URL. |
| `select-in-images` | `()` | Local: navigate to the Images page. |

## Worker `Request` inventory (`forza-gui/src/worker.rs`)

Each variant is handled by the pure `handle_request(ctx, service, request)`
(no widget types), so it is testable headlessly. Per-job threads run handlers
concurrently; responses marshal back via `slint::invoke_from_event_loop`.

| `Request` variant | Payload |
| --- | --- |
| `RefreshInventory` | `filter: ImageInventoryFilter` — list cached inventory reads. |
| `SyncInputFolder` | `filter: ImageInventoryFilter` — register new input-folder files, then list. |
| `ListReviews` | `filter: ReviewQueueFilter` — cases + dynamic filter options. |
| `ReopenCase` | `case_number: i64` — reopen + re-sync review flags. |
| `LoadPreview` | `image_file_id: String` — resolve the on-disk path for the preview. |
| `DecideCase` | `case_number: i64, field: String, value: String` — apply correction, then `rebuild()`. |
| `IgnoreCase` | `case_number: i64` — ignore + re-sync review flags. |
| `ListBestLaps` | — best-lap rows for the worker's live gamertag. |
| `RunDoctor` | — fast `doctor_on_path` report. |
| `RunFullDoctor` | — full audit (`run_full_doctor_on_path`). |
| `RunRebuild` | — `rebuild()` with the worker's live gamertag. |
| `RunDryRun` | `input_dir: String` — plan-only summary, no model calls. |
| `LoadImageDetail` | `image_id: String` — full image detail payload. |
| `RenameImages` | `image_ids: Vec<String>` — rename to semantic/current names. |
| `ExportImages` | `image_ids: Vec<String>, dest_dir: String` — copy with semantic names. |
| `RescanImages` | `image_ids: Vec<String>` — re-check on-disk existence. |
| `DeleteImages` | `image_ids: Vec<String>` — DB row first (FK RESTRICT may refuse), then file. |
| `LoadSettings` | — reload config from disk into the worker + fresh snapshot. |
| `PreviewSettings` | `changes: BTreeMap<String, String>, seq: u64` — validate without saving; `seq` echoed back. |
| `SaveSettings` | `changes: BTreeMap<String, String>` — backup + atomic write; gamertag change triggers `rebuild()`. |
| `ListImageDebugCases` | `filter: ImageDebugFilter` — image-centric debug case list. |
| `LoadImageDebugDetail` | `image_file_id: String, selected_result_id: Option<String>` — debug detail payload. |
| `LoadImageDebugByResult` | `extraction_result_id: String` — debug detail by result id. |
| `LoadLogs` | — app + error log tails (200 KB cap). |
| `ClearLogs` | `which: String` — truncate `app` or `errors` log. |
| `OpenLogFolder` | — open the log directory. |
| `RefreshOverview` | — diagnostics overview snapshot (LM Studio, DB, inventory, review). |
| `ImportExternalRecords` | `path: String` — `import_to_db`, then Best Laps reload. |

## Worker `Response` inventory

| `Response` variant | Payload |
| --- | --- |
| `Inventory` | `result: Vec<ImageInventoryEntry>`, `options: ImageInventoryOptions`, `filter_label: String`. |
| `Reviews` | `result: Vec<ReviewCaseEntry>`, `options: ReviewOptions`, `filter: ReviewQueueFilter`. |
| `CaseDecided` | `Result<(), String>` — reloads Reviews + Best Laps + Images on success. |
| `BestLaps` | `Result<Vec<BestLapRow>, String>` — cached as `BESTLAP_ALL`, filtered in memory. |
| `Doctor` | `Result<DoctorSummary, String>` — rendered into the doctor report + check list. |
| `Rebuild` | `Result<RebuildOutcome, String>` — reloads Reviews (all bucket) + Best Laps. |
| `RunDryRunDone` | `String` — plan summary appended to the run log. |
| `ImageDetail` | `Result<Option<ImageDetailData>, String>`. |
| `RenameDone` | `Result<String, String>` — summary message + Images reload. |
| `ExportDone` | `Result<(exported: usize, skipped: usize), String>`. |
| `RescanDone` | `Result<(available: usize, missing: usize), String>` + Images reload. |
| `DeleteDone` | `Result<(deleted: usize, refused: usize, sample: String), String>` + Images reload. |
| `Preview` | `Result<Option<String>, String>` — image file path (`None` when the case has no image). |
| `CaseReopen` | `Result<(), String>` — reloads Reviews. |
| `ImageDebugCases` | `Result<Vec<ImageDebugCase>, String>`. |
| `ImageDebugDetail` | `Result<Option<ImageDebugDetail>, String>`. |
| `Logs` | `Result<(app_log: String, error_log: String), String>`. |
| `ClearLogs` | `Result<String, String>` — then reloads logs. |
| `OpenLogFolder` | `Result<String, String>`. |
| `Overview` | `Result<OverviewSnapshot, String>`. |
| `Settings` | `Result<SettingsOutcome, String>` — fresh snapshot + effective config; `gamertag_recomputed` triggers derived-view reloads; stale `seq` previews dropped. |
| `ImportDone` | `Result<ExternalImportResult, String>` — summary shown after the Best Laps reload. |
| `Error` | `String` — a job thread panicked; resets the coalescing flags so later requests still issue. |

## Maintenance rule

- Do not add undocumented callbacks, `Request` variants, or `Response`
  variants. Add a row above in the same change.
- Prefer typed `Request`/`Response` payloads over untyped strings for new
  cross-boundary data.
- Keep Slint callback signatures stable; document payload changes here instead
  of relying on implicit handler knowledge.
- `RunEvent` values from the extraction thread (`Started`, `Plan`,
  `ImageStarted`, `ImageDone`, `Progress`, `Log`, `Finished`, `Failed`) stream
  through `spawn_extraction` directly, not through the worker channel; they
  are defined in `forza-app/src/services/extraction_runner.rs`.
