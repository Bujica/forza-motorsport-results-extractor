from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal

from ...config import AppConfig
from ..config_state import ConfigChangeSet
from ..workers.db_doctor_worker import DbDoctorWorker

_log = logging.getLogger("forza")


class DbDoctorController(QObject):
    report_changed = Signal(object)
    loading_changed = Signal(bool)
    action_failed = Signal(str)

    def __init__(self, *, cfg, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._thread: QThread | None = None
        self._worker: DbDoctorWorker | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def on_config_changed(self, cfg: AppConfig, changes: ConfigChangeSet) -> None:
        self._cfg = cfg
        if changes.affects("paths.database_file"):
            self.refresh()

    def refresh(self) -> None:
        if self.is_running:
            return
        self._thread = QThread(self)
        self._worker = DbDoctorWorker(database_file=self._cfg.database_file)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._clear_refs)
        self.loading_changed.emit(True)
        self._thread.start()

    def close(self) -> None:
        if self._thread is None or not self._thread.isRunning():
            return
        self._thread.quit()
        if not self._thread.wait(5000):
            _log.warning(
                "[gui] DbDoctorController: worker thread did not stop within 5s, forcing terminate()"
            )
            self._thread.terminate()
            self._thread.wait(1000)

    def _on_finished(self, result) -> None:
        self.loading_changed.emit(False)
        if result.ok and result.report is not None:
            self.report_changed.emit(result.report)
        else:
            self.action_failed.emit(result.message)

    def _clear_refs(self) -> None:
        self._thread = None
        self._worker = None
