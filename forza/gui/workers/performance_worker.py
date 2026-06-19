from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from ...application.gui_read_service import GuiReadService
from ...application.gui_read_service_best_laps import list_external_records
from ...application.performance_service import PerformanceDashboard, build_dashboard
from ...schemas import ExternalLapRecord


@dataclass(frozen=True)
class PerformanceWorkerResult:
    ok: bool
    dashboard: PerformanceDashboard | None = None
    external_records: list[ExternalLapRecord] | None = None
    message: str = ""


class PerformanceWorker(QObject):
    finished = Signal(object)

    def __init__(self, *, database_file: Any, gamertag: str) -> None:
        super().__init__()
        self._database_file = database_file
        self._gamertag = gamertag

    @Slot()
    def run(self) -> None:
        try:
            dashboard, external_records = _load_performance_dashboard(
                database_file=self._database_file,
                gamertag=self._gamertag,
            )
            payload = PerformanceWorkerResult(
                ok=True,
                dashboard=dashboard,
                external_records=external_records,
            )
        except Exception as exc:  # pragma: no cover - GUI boundary
            payload = PerformanceWorkerResult(ok=False, message=str(exc))
        self.finished.emit(payload)


def _load_performance_dashboard(*, database_file: Any, gamertag: str) -> tuple[PerformanceDashboard, list[ExternalLapRecord]]:
    reader = GuiReadService(database_file)
    try:
        laps = reader.list_laps()
        external_records = list_external_records(reader)
        dashboard = build_dashboard(laps, gamertag=gamertag, external_records=external_records)
    finally:
        reader.close()
    return dashboard, external_records
