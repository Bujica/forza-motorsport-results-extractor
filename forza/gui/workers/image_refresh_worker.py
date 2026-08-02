from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from ...application.gui_read_service import GuiImage, GuiReadService


@dataclass(frozen=True)
class ImageRefreshFilterOptions:
    tracks: list[str]
    runs: list[object]


@dataclass(frozen=True)
class ImageRefreshWorkerResult:
    ok: bool
    images: list[GuiImage] | None = None
    filter_options: ImageRefreshFilterOptions | None = None
    message: str = ""


class ImageRefreshWorker(QObject):
    finished = Signal(object)

    def __init__(
        self,
        *,
        database_file: Any,
        file_status: str | None,
        best_lap_status: str | None,
        inventory_filter: str | None,
        track: str | None,
        run_id: str | None,
        processing_status: str | None,
    ) -> None:
        super().__init__()
        self._database_file = database_file
        self._file_status = file_status
        self._best_lap_status = best_lap_status
        self._inventory_filter = inventory_filter
        self._track = track
        self._run_id = run_id
        self._processing_status = processing_status

    @Slot()
    def run(self) -> None:
        # A fresh, worker-thread-local reader — never share the controller's
        # own GuiReadService/session across threads.
        reader = GuiReadService(self._database_file)
        try:
            images = reader.list_images(
                file_status=self._file_status,
                best_lap_status=self._best_lap_status,
                inventory_filter=self._inventory_filter,
                track=self._track,
                run_id=self._run_id,
                processing_status=self._processing_status,
            )
            tracks, runs = reader.image_filter_values(
                file_status=self._file_status,
                best_lap_status=self._best_lap_status,
                inventory_filter=self._inventory_filter,
                track=self._track,
                run_id=self._run_id,
                processing_status=self._processing_status,
            )
            payload = ImageRefreshWorkerResult(
                ok=True,
                images=images,
                filter_options=ImageRefreshFilterOptions(tracks=tracks, runs=runs),
            )
        except Exception as exc:  # pragma: no cover - GUI boundary
            payload = ImageRefreshWorkerResult(ok=False, message=str(exc))
        finally:
            reader.close()
        self.finished.emit(payload)
