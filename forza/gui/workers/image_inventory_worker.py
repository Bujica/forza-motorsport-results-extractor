from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from ...application import DatabaseService, ImageInventoryService, InputFolderScanResult


@dataclass(frozen=True)
class ImageInventoryWorkerResult:
    ok: bool
    scan_result: InputFolderScanResult | None = None
    message: str = ""


class ImageInventoryWorker(QObject):
    finished = Signal(object)

    def __init__(self, *, database_file: Any, input_dir: Any) -> None:
        super().__init__()
        self._database_file = database_file
        self._input_dir = input_dir

    @Slot()
    def run(self) -> None:
        try:
            result = _scan_input_folder(
                database_file=self._database_file,
                input_dir=self._input_dir,
            )
            payload = ImageInventoryWorkerResult(ok=True, scan_result=result)
        except Exception as exc:  # pragma: no cover - GUI boundary
            payload = ImageInventoryWorkerResult(ok=False, message=str(exc))
        self.finished.emit(payload)


def _scan_input_folder(*, database_file: Any, input_dir: Any) -> InputFolderScanResult:
    with DatabaseService(database_file) as database:
        return ImageInventoryService(database).scan_input_folder(Path(input_dir))
