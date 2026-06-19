from __future__ import annotations

from pathlib import Path


GUI_ROOT = Path(__file__).resolve().parents[1] / "forza" / "gui"


def test_process_worker_uses_public_run_service_boundary() -> None:
    source = (GUI_ROOT / "workers" / "run_worker.py").read_text(encoding="utf-8")

    assert "RunService" in source
    assert "RunOptions" in source
    assert "selected_image_file_ids" in source
    assert "load_reference_data" in source
    assert "setup_logging" in source


def test_process_controller_runs_worker_in_qthread_and_uses_event_bridge() -> None:
    source = (GUI_ROOT / "controllers" / "process_controller.py").read_text(encoding="utf-8")

    assert "QThread" in source
    assert "QtEventBridge" in source
    assert "moveToThread(self._thread)" in source
    assert "event_sink=self._bridge.sink" in source
    assert "self._bridge.moveToThread" not in source


def test_process_view_contains_required_stage_two_controls() -> None:
    source = (GUI_ROOT / "views" / "process_view.py").read_text(encoding="utf-8")

    for token in (
        "Run Config",
        "lmstudio ·",
        "self._cfg.llm.model",
        "prompt {self._cfg.prompt.active}",
        "_execution_label(self._cfg.workers)",
        "Execution: Sequential",
        "Execution: Parallel",
        "self._cfg.llm.image_format",
        "self._cfg.image.max_width",
        "self._cfg.image.encode_quality",
        "self._cfg.image.grayscale",
        "_pending_screenshots",
        "SUPPORTED_IMAGE_EXTENSIONS",
        "Dry-run",
        "Force",
        "Retry errors",
        "Debug",
        "Run All",
        "Select in Images",
        "Pause",
        "Resume",
        "Cancel",
        "pause_requested",
        "resume_requested",
        "cancel_requested",
        "Cancel after the current image?",
        "ETA:",
        "_duration_text",
        "_FINAL_RUN_STATUSES",
        "Total:",
        "img/min",
    ):
        assert token in source
    assert "Open logs" not in source
    assert "run_all_requested" in source
    assert "select_images_requested" in source
    assert "def run_options(" in source
    assert "QSpinBox" not in source
    assert "self.start_requested.emit(" not in source


def test_run_service_supports_gui_selected_image_files() -> None:
    controller = (GUI_ROOT / "controllers" / "process_controller.py").read_text(encoding="utf-8")
    worker = (GUI_ROOT / "workers" / "run_worker.py").read_text(encoding="utf-8")
    run = (GUI_ROOT.parents[0] / "application" / "run_service.py").read_text(encoding="utf-8")

    assert "selected_image_file_ids" in controller
    assert "selected_image_file_ids" in worker
    assert "selected_image_file_ids" in run
    assert "selected_image_file_ids=selected_ids" in (GUI_ROOT / "main_window.py").read_text(encoding="utf-8")
    assert "def _selected_files" in run
    assert "database.selected_image_files" not in run
    assert "selected_image_file_count" in run


def test_process_controller_and_worker_support_cooperative_control() -> None:
    controller = (GUI_ROOT / "controllers" / "process_controller.py").read_text(encoding="utf-8")
    worker = (GUI_ROOT / "workers" / "run_worker.py").read_text(encoding="utf-8")
    extraction = (GUI_ROOT.parents[0] / "application" / "extraction_service.py").read_text(encoding="utf-8")
    run = (GUI_ROOT.parents[0] / "application" / "run_service.py").read_text(encoding="utf-8")

    for token in ("pause_run", "resume_run", "cancel_run", "pause_state_changed"):
        assert token in controller
    for token in ("RunControl", "request_pause", "request_resume", "request_cancel"):
        assert token in worker
    assert "run_control.checkpoint()" in run
    assert "self.run_control.checkpoint()" in extraction
    assert "RunStatus.CANCELLED" in run


def test_run_logs_operator_progress_without_hash_noise() -> None:
    extraction = (GUI_ROOT.parents[0] / "application" / "extraction_service.py").read_text(encoding="utf-8")
    pipeline = (GUI_ROOT.parents[0] / "pipeline" / "process.py").read_text(encoding="utf-8")
    run = (GUI_ROOT.parents[0] / "application" / "run_service.py").read_text(encoding="utf-8")
    process_view = (GUI_ROOT / "views" / "process_view.py").read_text(encoding="utf-8")
    logs_view = (GUI_ROOT / "views" / "logs_view.py").read_text(encoding="utf-8")

    assert "display_name = result.semantic_name or result.source_file" in extraction
    assert "f\"[{done}/{total} {status}] {display_name}{suffix}\"" in extraction
    assert "log.debug(\n        f\"[pipeline] OK" in pipeline
    assert "log.debug(f\"  process: {path.name}  hash={file_hash}\")" in run
    assert "log.info(f\"  process: {path.name}\")" in run
    assert "file_hash[:12]" not in run
    assert "format_runtime_event" in process_view
    assert "image_started" in logs_view
    assert "batch_started" in logs_view
    assert "file_hash" in logs_view


def test_main_window_closes_worker_backed_controllers() -> None:
    source = (GUI_ROOT / "main_window.py").read_text(encoding="utf-8")

    for token in (
        "self._process_controller,",
        "self._rebuild_controller,",
    ):
        assert token in source

    for controller in (
        "process_controller.py",
        "rebuild_controller.py",
    ):
        controller_source = (GUI_ROOT / "controllers" / controller).read_text(encoding="utf-8")
        assert "def close(self)" in controller_source
        assert ".wait(5000)" in controller_source


def test_main_window_exposes_application_version() -> None:
    source = (GUI_ROOT / "main_window.py").read_text(encoding="utf-8")
    app = (GUI_ROOT / "app.py").read_text(encoding="utf-8")

    assert "APP_DISPLAY_VERSION" in source
    assert "self.setWindowTitle(APP_DISPLAY_VERSION)" in source
    assert "QLabel(f\"v{__version__}\")" in source
    assert "status.showMessage(f\"v{__version__}" in source
    assert "app.setApplicationVersion(__version__)" in app
