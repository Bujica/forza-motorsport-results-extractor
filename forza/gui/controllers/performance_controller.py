from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

from ...application import DatabaseService, ExternalImportResult, ExternalRecordService
from ...config import AppConfig
from ...events import EventType, PipelineEvent
from ..config_state import ConfigChangeSet
from ..workers.performance_worker import PerformanceWorker, PerformanceWorkerResult


class PerformanceController(QObject):
    dashboard_changed = Signal(object)
    external_records_changed = Signal(object)
    loading_changed = Signal(bool)
    action_completed = Signal(str)
    action_failed = Signal(str)

    def __init__(self, *, cfg: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._gamertag = str(cfg.gamertag or "").lower()
        self._cfg = cfg
        self._external_records_service = ExternalRecordService()
        self._thread: QThread | None = None
        self._worker: PerformanceWorker | None = None
        self._refresh_pending = False

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def on_config_changed(self, cfg: AppConfig, changes: ConfigChangeSet) -> None:
        if changes.affects("user.gamertag"):
            self._gamertag = str(cfg.gamertag or "").lower()
        self._cfg = cfg
        if changes.affects("paths.database_file") or changes.affects("user.gamertag"):
            self._refresh_pending = self.is_running

    def close(self) -> None:
        if self._thread is None or not self._thread.isRunning():
            return
        self._thread.quit()
        if not self._thread.wait(5000):
            self._thread.terminate()
            self._thread.wait(1000)

    def refresh(self) -> None:
        if self.is_running:
            self._refresh_pending = True
            return
        self._thread = QThread(self)
        self._worker = PerformanceWorker(database_file=self._cfg.database_file, gamertag=self._gamertag)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._clear_worker_refs)

        self.loading_changed.emit(True)
        self._thread.start()

    def import_external_records(self, path: Path) -> None:
        try:
            with DatabaseService(self._cfg.database_file) as database:
                result = self._external_records_service.import_to_db(database, path)
        except Exception as exc:
            self.action_failed.emit(f"External records import failed: {exc}")
            return
        self.action_completed.emit(_external_import_message(result))
        self.refresh()

    def handle_event(self, event: PipelineEvent) -> None:
        if event.type in {EventType.IMAGE_FINISHED, EventType.RUN_FINISHED, EventType.LAP_RECORD_CORRECTED}:
            self.refresh()

    def _on_worker_finished(self, result: PerformanceWorkerResult) -> None:
        self.loading_changed.emit(False)
        if result.ok and result.dashboard is not None:
            self.dashboard_changed.emit(result.dashboard)
            self.external_records_changed.emit(result.external_records or [])
        else:
            self.action_failed.emit(result.message or "Performance dashboard refresh failed.")

    def _clear_worker_refs(self) -> None:
        self._thread = None
        self._worker = None
        if self._refresh_pending:
            self._refresh_pending = False
            self.refresh()


def _external_import_message(result: ExternalImportResult) -> str:
    return (
        f"External records imported: {len(result.records)} record(s) from "
        f"{result.total_rows} row(s). "
        f"Rejected rows: {result.rejected_rows}. Warnings: {result.warning_count}. "
        f"Unmapped tracks: {result.unmapped_tracks}. "
        f"Missing required fields: {result.missing_required_fields}. "
        f"Invalid laps: {result.invalid_laps}. Weather: dry assumed."
    )
