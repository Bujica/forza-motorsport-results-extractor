from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices

from ...config import AppConfig
from ..config_state import ConfigChangeSet, GuiConfigState
from ..workers.event_bridge import QtEventBridge
from ..workers.rebuild_worker import RebuildWorker, RebuildWorkerResult


class RebuildController(QObject):
    rebuild_started = Signal()
    rebuild_finished = Signal(object)
    log_line_received = Signal(str)
    event_received = Signal(object)
    action_completed = Signal(str)
    action_failed = Signal(str)

    def __init__(
        self,
        *,
        config_state: GuiConfigState | None = None,
        cfg: Any | None = None,
        debug: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        inherited_state = getattr(parent, "_config_state", None)
        if config_state is None and isinstance(inherited_state, GuiConfigState):
            config_state = inherited_state
        if config_state is None:
            raise TypeError("RebuildController requires GuiConfigState")
        self._config_state = config_state
        self._debug = debug
        self._thread: QThread | None = None
        self._worker: RebuildWorker | None = None
        self._bridge: QtEventBridge | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def on_config_changed(self, _cfg: AppConfig, _changes: ConfigChangeSet) -> None:
        # Rebuild actions read config_state.current at action time. An in-flight
        # rebuild owns its start-time snapshot and is not mutated by later saves.
        return

    def close(self) -> None:
        if self._thread is None or not self._thread.isRunning():
            return
        self._thread.quit()
        if not self._thread.wait(5000):
            self._thread.terminate()
            self._thread.wait(1000)

    def start_rebuild(self) -> bool:
        if self.is_running:
            return False
        cfg = self._config_state.current
        self._thread = QThread(self)
        self._bridge = QtEventBridge()
        self._worker = RebuildWorker(cfg=cfg, debug=self._debug, event_sink=self._bridge.sink)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.log_line.connect(self.log_line_received)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._bridge.event_received.connect(self.event_received)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._clear_refs)

        self.rebuild_started.emit()
        self._thread.start()
        return True

    def open_last_pdf(self) -> bool:
        path = Path(self._config_state.current.pdf_file)
        if not path.exists():
            self.action_failed.emit(f"PDF not found: {path}")
            return False
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))
        return True

    def _on_finished(self, result: RebuildWorkerResult) -> None:
        self.rebuild_finished.emit(result)
        if result.ok:
            self.action_completed.emit(result.message)
            if result.pdf_path and result.pdf_path.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(result.pdf_path.resolve())))
        else:
            self.action_failed.emit(result.message)

    def _clear_refs(self) -> None:
        self._thread = None
        self._worker = None
        self._bridge = None
