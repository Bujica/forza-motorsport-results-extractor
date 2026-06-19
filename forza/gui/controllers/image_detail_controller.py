from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from ...application.gui_read_service import GuiExtractionAttempt, GuiExtractionResult, GuiLap, GuiReadService, GuiReviewCase
from ...config import AppConfig
from ...schemas import ImageFile
from ..config_state import ConfigChangeSet


@dataclass(frozen=True)
class ImageDetail:
    image: ImageFile
    preview_path: Path | None
    laps: list[GuiLap]
    review_cases: list[GuiReviewCase]
    extraction_results: list[GuiExtractionResult]
    extraction_attempts: list[GuiExtractionAttempt]


class ImageDetailController(QObject):
    detail_loaded = Signal(object)
    detail_failed = Signal(str)
    open_debug_requested = Signal(str)

    def __init__(self, *, cfg: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._reader = GuiReadService(cfg.database_file)
        self._current_detail: ImageDetail | None = None

    def on_config_changed(self, cfg: AppConfig, changes: ConfigChangeSet) -> None:
        self._cfg = cfg
        if not changes.affects("paths.database_file"):
            return
        self._reader.close()
        self._reader = GuiReadService(cfg.database_file)
        self._current_detail = None

    def close(self) -> None:
        self._reader.close()

    def load_image(self, image_file_id: str) -> None:
        image = self._reader.get_image(image_file_id)
        if image is None:
            self._current_detail = None
            self.detail_failed.emit(f"Image not found: {image_file_id}")
            return
        detail = ImageDetail(
            image=image,
            preview_path=Path(image.current_path) if image.current_path else None,
            laps=self._reader.list_laps(image_file_id=image_file_id),
            review_cases=self._reader.list_review_queue(status="all", image_file_id=image_file_id),
            extraction_results=self._reader.list_extraction_results(image_file_id=image_file_id),
            extraction_attempts=self._reader.list_extraction_attempts(image_file_id=image_file_id),
        )
        self._current_detail = detail
        self.detail_loaded.emit(detail)

    def request_open_debug(self, extraction_result_id: str | None = None) -> None:
        if self._current_detail is None:
            self.detail_failed.emit("No image loaded.")
            return
        results = self._current_detail.extraction_results
        if not results:
            self.detail_failed.emit("The image has no linked extraction result.")
            return
        if extraction_result_id is not None:
            result_ids = {result.id for result in results}
            if extraction_result_id not in result_ids:
                self.detail_failed.emit("Selected extraction result is not linked to this image.")
                return
            self.open_debug_requested.emit(extraction_result_id)
            return
        fallback_id = _latest_extraction_result_id(results)
        if fallback_id is None:
            self.detail_failed.emit("The image has no linked extraction result.")
            return
        self.open_debug_requested.emit(fallback_id)


def _latest_extraction_result_id(results) -> str | None:
    dated = [result for result in results if getattr(result, "created_at", None) is not None]
    if dated:
        return max(dated, key=lambda result: str(getattr(result, "created_at", ""))).id
    return results[0].id if results else None
