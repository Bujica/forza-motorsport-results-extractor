from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ...config import AppConfig
from ...application import DbDoctorService
from ..config_state import ConfigChangeSet


class DbDoctorController(QObject):
    report_changed = Signal(object)
    action_failed = Signal(str)

    def __init__(self, *, cfg, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._service = DbDoctorService()

    def on_config_changed(self, cfg: AppConfig, changes: ConfigChangeSet) -> None:
        self._cfg = cfg
        if changes.affects("paths.database_file"):
            self.refresh()

    def refresh(self) -> None:
        try:
            self.report_changed.emit(self._service.run(self._cfg.database_file))
        except Exception as exc:
            self.action_failed.emit(str(exc))
