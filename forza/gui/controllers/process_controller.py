from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

from ...config import AppConfig
from ...events import EventType, PipelineEvent
from ..config_state import ConfigChangeSet, GuiConfigState
from ..workers.event_bridge import QtEventBridge
from ..workers.run_worker import RunRequest, RunWorker, RunWorkerResult


@dataclass(frozen=True)
class ProcessSummary:
    status: str
    run_id: str | None = None
    total: int = 0
    to_process: int = 0
    processed: int = 0
    errors: int = 0
    duplicates: int = 0
    review_cases: int = 0
    elapsed_s: float = 0.0
    rate_per_min: float = 0.0
    dry_run: bool = False
    retry_errors: bool = False
    input_total: int = 0


class ProcessController(QObject):
    """Controller boundary for the Process screen."""

    run_started = Signal()
    run_finished = Signal(object)
    pause_state_changed = Signal(bool)
    event_received = Signal(object)
    log_line_received = Signal(str)
    summary_changed = Signal(object)

    def __init__(self, *, config_state: GuiConfigState, debug: bool = False, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config_state = config_state
        self._cfg = config_state.current
        self._debug = debug
        self._thread: QThread | None = None
        self._worker: RunWorker | None = None
        self._bridge: QtEventBridge | None = None
        self._started_at: float | None = None
        self._paused_at: float | None = None
        self._paused_total_s = 0.0
        self._run_id: str | None = None
        self._total = 0
        self._input_total = 0
        self._to_process = 0
        self._processed = 0
        self._errors = 0
        self._duplicates = 0
        self._review_cases = 0
        self._dry_run = False
        self._retry_errors = False
        self._status = "idle"

    @property
    def cfg(self) -> Any:
        return self._cfg

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def on_config_changed(self, cfg: AppConfig, _changes: ConfigChangeSet) -> None:
        if self.is_running:
            return
        self._cfg = cfg

    def close(self) -> None:
        if self._worker is not None:
            self._worker.request_cancel()
        if self._thread is None or not self._thread.isRunning():
            return
        self._thread.quit()
        if not self._thread.wait(5000):
            self._thread.terminate()
            self._thread.wait(1000)

    def start_run(
        self,
        dry_run: bool,
        force: bool,
        retry_errors: bool = False,
        debug: bool = False,
        selected_image_file_ids: object | None = None,
    ) -> bool:
        if self.is_running:
            return False

        try:
            run_cfg = self._load_run_config()
        except Exception as exc:
            self._status = "failed"
            self.run_finished.emit(RunWorkerResult(status="failed", error=str(exc)))
            self.summary_changed.emit(self._summary("failed"))
            return False

        self._reset_state(dry_run=dry_run, retry_errors=retry_errors)
        self._thread = QThread(self)
        self._bridge = QtEventBridge()
        self._worker = RunWorker(
            cfg=run_cfg,
            request=RunRequest(
                dry_run=dry_run,
                force=force,
                retry_errors=retry_errors,
                debug=debug or self._debug,
                selected_image_file_ids=_image_file_ids(selected_image_file_ids),
            ),
            event_sink=self._bridge.sink,
        )
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.log_line.connect(self.log_line_received)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._bridge.event_received.connect(self._on_pipeline_event)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._clear_worker_refs)

        self.run_started.emit()
        self._status = "running"
        self.summary_changed.emit(self._summary("running"))
        self._thread.start()
        return True

    def pause_run(self) -> bool:
        if self._worker is None or not self.is_running:
            return False
        self._worker.request_pause()
        if self._paused_at is None:
            self._paused_at = time.monotonic()
        self._status = "paused"
        self.pause_state_changed.emit(True)
        self.summary_changed.emit(self._summary("paused"))
        return True

    def resume_run(self) -> bool:
        if self._worker is None or not self.is_running:
            return False
        self._worker.request_resume()
        self._finish_pause()
        self._status = "running"
        self.pause_state_changed.emit(False)
        self.summary_changed.emit(self._summary("running"))
        return True

    def cancel_run(self) -> bool:
        if self._worker is None or not self.is_running:
            return False
        self._worker.request_cancel()
        self._finish_pause()
        self._status = "cancelling"
        self.pause_state_changed.emit(False)
        self.summary_changed.emit(self._summary("cancelling"))
        return True

    def _load_run_config(self) -> Any:
        self._cfg = self._config_state.reload(strict=True, emit=True)
        return self._cfg

    def _reset_state(self, *, dry_run: bool, retry_errors: bool = False) -> None:
        self._started_at = time.monotonic()
        self._paused_at = None
        self._paused_total_s = 0.0
        self._run_id = None
        self._total = 0
        self._input_total = 0
        self._to_process = 0
        self._processed = 0
        self._errors = 0
        self._duplicates = 0
        self._review_cases = 0
        self._dry_run = dry_run
        self._retry_errors = retry_errors
        self._status = "running"

    def _on_pipeline_event(self, event: PipelineEvent) -> None:
        self.event_received.emit(event)
        self._run_id = event.run_id or self._run_id
        if event.type == EventType.IMAGES_DISCOVERED:
            self._total = int(event.data.get("total") or 0)
            self._input_total = int(event.data.get("input_total") or self._total)
            self._duplicates = int(event.data.get("duplicates") or 0)
            self._to_process = int(event.data.get("to_process") or 0)
            self._dry_run = bool(event.data.get("dry_run") or self._dry_run)
            self._retry_errors = bool(event.data.get("retry_errors") or self._retry_errors)
        elif event.type == EventType.IMAGE_FINISHED:
            self._processed = int(event.data.get("done") or self._processed)
            if str(event.data.get("status")) != "ok":
                self._errors += 1
        elif event.type == EventType.RUN_FINISHED:
            self._status = str(event.data.get("status") or self._status)
            self._processed = int(event.data.get("processed") or self._processed)
            self._errors = int(event.data.get("errors") or self._errors)
            self._duplicates = int(event.data.get("duplicates") or self._duplicates)
            self._review_cases = int(event.data.get("review_cases") or self._review_cases)
        self.summary_changed.emit(self._summary(self._status))

    def _on_worker_finished(self, result: RunWorkerResult) -> None:
        self._finish_pause()
        status = str(result.status)
        self._status = status
        self.pause_state_changed.emit(False)
        summary = self._summary(status)
        self.summary_changed.emit(summary)
        self.run_finished.emit(result)

    def _clear_worker_refs(self) -> None:
        self._thread = None
        self._worker = None
        self._bridge = None

    def _summary(self, status: str) -> ProcessSummary:
        paused_now = time.monotonic() - self._paused_at if self._paused_at is not None else 0.0
        elapsed = (
            max(0.0, time.monotonic() - self._started_at - self._paused_total_s - paused_now)
            if self._started_at
            else 0.0
        )
        rate = (self._processed / elapsed * 60.0) if elapsed > 0 and self._processed else 0.0
        return ProcessSummary(
            status=status,
            run_id=self._run_id,
            total=self._total,
            input_total=self._input_total,
            to_process=self._to_process,
            processed=self._processed,
            errors=self._errors,
            duplicates=self._duplicates,
            review_cases=self._review_cases,
            elapsed_s=elapsed,
            rate_per_min=rate,
            dry_run=self._dry_run,
            retry_errors=self._retry_errors,
        )

    def _finish_pause(self) -> None:
        if self._paused_at is None:
            return
        self._paused_total_s += time.monotonic() - self._paused_at
        self._paused_at = None


def _image_file_ids(value: object | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, str):
        ids = (value,)
    else:
        try:
            ids = tuple(str(item) for item in value if str(item))
        except TypeError:
            ids = (str(value),)
    return ids or None
