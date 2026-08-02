from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from ...application import DbDoctorReport, DbDoctorService


@dataclass(frozen=True)
class DbDoctorWorkerResult:
    ok: bool
    report: DbDoctorReport | None = None
    message: str = ""


class DbDoctorWorker(QObject):
    finished = Signal(object)

    def __init__(self, *, database_file: Path) -> None:
        super().__init__()
        self._database_file = database_file

    @Slot()
    def run(self) -> None:
        try:
            report = DbDoctorService().run(self._database_file)
            payload = DbDoctorWorkerResult(ok=True, report=report)
        except Exception as exc:  # pragma: no cover - GUI boundary
            payload = DbDoctorWorkerResult(ok=False, message=str(exc))
        self.finished.emit(payload)
