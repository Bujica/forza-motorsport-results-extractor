# GUI Signal(object) Payload Contracts

Status: current  
Audience: developer, maintainer, LLM  
Lifecycle: permanent  
Scope: PySide6 GUI signal payload documentation  
Last verified: 2026-06-09

PySide6 `Signal(object)` is used where the GUI passes Python dataclasses, lists,
dicts, or domain DTOs across controller/view/worker boundaries. Keep the Qt
signature as `object` unless a native Qt type is both sufficient and stable.

When adding or changing a `Signal(...object...)`, update this document in the
same patch. The static test `tests/test_gui_signal_object_payload_docs_static.py`
checks that every object-typed GUI signal has a documented entry.

## Contract table

| Signal marker | Declared signature | Payload contract |
| --- | --- | --- |
| `forza/gui/config_state.py::changed` | `Signal(object, object)` | GUI DTO/dataclass/list/dict payload; keep documented with the emitting method. |
| `forza/gui/controllers/best_laps_controller.py::rows_changed` | `Signal(object)` | `list[BestLapRow]` displayed by Best Laps. |
| `forza/gui/controllers/best_laps_controller.py::filter_options_changed` | `Signal(object)` | `BestLapFilterOptions` for Best Laps filter widgets. |
| `forza/gui/controllers/db_doctor_controller.py::report_changed` | `Signal(object)` | updated controller/view model object for the corresponding GUI section. |
| `forza/gui/controllers/developer_overview_controller.py::overview_changed` | `Signal(object)` | updated controller/view model object for the corresponding GUI section. |
| `forza/gui/controllers/image_controller.py::images_changed` | `Signal(object)` | `list[ImageFile]` for the image browser table. |
| `forza/gui/controllers/image_controller.py::filter_options_changed` | `Signal(object)` | `ImageFilterOptions` for image-browser filters. |
| `forza/gui/controllers/image_controller.py::selection_detail_changed` | `Signal(object, object)` | `tuple[list[ImageFile], ImageFile | None]` selection detail payload. |
| `forza/gui/controllers/image_detail_controller.py::detail_loaded` | `Signal(object)` | loaded DTO/detail object for the corresponding GUI section. |
| `forza/gui/controllers/image_debug_controller.py::cases_changed` | `Signal(object)` | `list[GuiImageDebugSummary]` current image-centric debug case list. |
| `forza/gui/controllers/image_debug_controller.py::detail_loaded` | `Signal(object)` | `GuiImageDebugDetail` selected image debug detail, including image metadata, results, attempts, artifacts, runtime, laps, reviews, and timeline. |
| `forza/gui/controllers/performance_controller.py::dashboard_changed` | `Signal(object)` | `PerformanceDashboard` aggregate dashboard payload. |
| `forza/gui/controllers/performance_controller.py::external_records_changed` | `Signal(object)` | `list[object]` external-record DTOs from application service. |
| `forza/gui/controllers/process_controller.py::run_finished` | `Signal(object)` | `RunWorkerResult` final process-run summary. |
| `forza/gui/controllers/process_controller.py::event_received` | `Signal(object)` | `PipelineEvent` received from extraction worker. |
| `forza/gui/controllers/process_controller.py::summary_changed` | `Signal(object)` | `ProcessSummary` snapshot for process status widgets. |
| `forza/gui/controllers/rebuild_controller.py::rebuild_finished` | `Signal(object)` | GUI DTO/dataclass/list/dict payload; keep documented with the emitting method. |
| `forza/gui/controllers/rebuild_controller.py::event_received` | `Signal(object)` | GUI DTO/dataclass/list/dict payload; keep documented with the emitting method. |
| `forza/gui/controllers/review_controller.py::queue_changed` | `Signal(object)` | `list[GuiReviewCase]` current review queue. |
| `forza/gui/controllers/review_controller.py::filter_options_changed` | `Signal(object)` | `dict[str, list[str]]` review filter options. |
| `forza/gui/controllers/review_controller.py::run_options_changed` | `Signal(object)` | `list[object]` run option DTOs from GUI read facade. |
| `forza/gui/controllers/review_controller.py::selection_changed` | `Signal(object, object, object, object)` | `tuple[GuiReviewCase | None, object | None, list[GuiLap], Path | None]` selection detail payload. |
| `forza/gui/controllers/settings_controller.py::settings_changed` | `Signal(object)` | updated controller/view model object for the corresponding GUI section. |
| `forza/gui/views/best_laps_view.py::export_requested` | `Signal(object)` | view intent/model object emitted to the owning controller. |
| `forza/gui/views/best_laps_view.py::import_external_records_requested` | `Signal(object)` | view intent/model object emitted to the owning controller. |
| `forza/gui/views/image_browser_view.py::refresh_requested` | `Signal(str, str, str, str, str, str)` | `tuple[file_status, best_lap_status, flag, track_id, run_id, processing_status]` image-browser filter state. |
| `forza/gui/views/image_browser_view.py::process_selected_requested` | `Signal(object)` | `tuple[str, ...]` selected `ImageFile` ids to process from the Images page. |
| `forza/gui/views/image_browser_view.py::selection_changed` | `Signal(object)` | updated controller/view model object for the corresponding GUI section. |
| `forza/gui/views/image_browser_view.py::rename_requested` | `Signal(object)` | view intent/model object emitted to the owning controller. |
| `forza/gui/views/image_browser_view.py::export_requested` | `Signal(object, object)` | view intent/model object emitted to the owning controller. |
| `forza/gui/views/image_browser_view.py::delete_requested` | `Signal(object)` | `tuple[str, ...]` selected `ImageFile` ids whose physical files and database records should be deleted. |
| `forza/gui/views/image_browser_view.py::rescan_selected_requested` | `Signal(object)` | `tuple[str, ...]` selected `ImageFile` ids to reconcile against current filesystem state. |
| `forza/gui/views/review_queue_view.py::refresh_requested` | `Signal(str, object, object, object)` | view intent/model object emitted to the owning controller. |
| `forza/gui/views/review_queue_view.py::filters_changed` | `Signal(str, object, object, object)` | updated controller/view model object for the corresponding GUI section. |
| `forza/gui/views/settings_view.py::preview_requested` | `Signal(object)` | view intent/model object emitted to the owning controller. |
| `forza/gui/views/settings_view.py::save_requested` | `Signal(object)` | view intent/model object emitted to the owning controller. |
| `forza/gui/workers/developer_overview_worker.py::finished` | `Signal(object)` | worker result dataclass or service result object emitted when background work completes. |
| `forza/gui/workers/event_bridge.py::event_received` | `Signal(object)` | `PipelineEvent` forwarded from worker thread to GUI thread. |
| `forza/gui/workers/image_inventory_worker.py::finished` | `Signal(object)` | `ImageInventoryWorkerResult` emitted when the background Images input-folder sync completes. |
| `forza/gui/workers/performance_worker.py::finished` | `Signal(object)` | `PerformanceWorkerResult` emitted when the background Records/Performance refresh completes. |
| `forza/gui/workers/model_list_worker.py::finished` | `Signal(object)` | worker result dataclass or service result object emitted when background work completes. |
| `forza/gui/workers/rebuild_worker.py::finished` | `Signal(object)` | worker result dataclass or service result object emitted when background work completes. |
| `forza/gui/workers/run_worker.py::finished` | `Signal(object)` | worker result dataclass or service result object emitted when background work completes. |

## Maintenance rule

- Do not add undocumented `Signal(...object...)` declarations. Add a row above in the same change.
- Prefer controller/view/worker DTO dataclasses over raw dicts for new cross-boundary payloads.
- Keep PySide signal signatures stable; document payload changes here instead of relying on implicit emitter knowledge.
