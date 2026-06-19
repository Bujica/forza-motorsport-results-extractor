from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal

from ...application.gui_read_service import GuiReadService
from ...config import AppConfig
from ...events import EventType, PipelineEvent
from ..config_state import ConfigChangeSet


class ImageDebugController(QObject):
    cases_changed = Signal(object)
    detail_loaded = Signal(object)
    detail_failed = Signal(str)

    def __init__(self, *, cfg: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._reader = _reader_for(cfg)
        self._status: str | None = None
        self._backend: str | None = None
        self._model: str | None = None
        self._prompt_name: str | None = None
        self._run_id: str | None = None
        self._cases = []
        self._selected_image_file_id: str | None = None
        self._selected_result_id: str | None = None

    def on_config_changed(self, cfg: AppConfig, changes: ConfigChangeSet) -> None:
        if not changes.affects("paths.database_file"):
            return
        self._reader.close()
        self._reader = _reader_for(cfg)
        self._cases = []
        self._selected_image_file_id = None
        self._selected_result_id = None
        self.cases_changed.emit(self._cases)

    def close(self) -> None:
        self._reader.close()

    def refresh(
        self,
        status: str | None = "all",
        backend: str | None = "all",
        model: str | None = "all",
        prompt_name: str | None = "all",
        run_id: str | None = "all",
    ) -> None:
        self._status = _none_for_all(status)
        self._backend = _none_for_all(backend)
        self._model = _none_for_all(model)
        self._prompt_name = _none_for_all(prompt_name)
        self._run_id = _none_for_all(run_id)
        self._cases = self._reader.list_image_debug_cases(
            status=self._status,
            backend=self._backend,
            model=self._model,
            prompt_name=self._prompt_name,
            run_id=self._run_id,
        )
        self.cases_changed.emit(self._cases)

    def select_image(self, image_file_id: str) -> None:
        self._selected_image_file_id = image_file_id
        self._selected_result_id = None
        detail = self._reader.get_image_debug_case(image_file_id)
        if detail is None:
            self.detail_failed.emit(f"Image not found: {image_file_id}")
            return
        self._selected_result_id = detail.selected_result_id
        self.detail_loaded.emit(detail)

    def select_result(self, image_file_id: str, extraction_result_id: str) -> None:
        self._selected_image_file_id = image_file_id
        self._selected_result_id = extraction_result_id
        detail = self._reader.get_image_debug_case(image_file_id, selected_result_id=extraction_result_id)
        if detail is None:
            self.detail_failed.emit(f"Image not found: {image_file_id}")
            return
        self.detail_loaded.emit(detail)

    def load_result(self, extraction_result_id: str) -> None:
        detail = self._reader.get_image_debug_case_by_result(extraction_result_id)
        if detail is None:
            self.detail_failed.emit(f"Extraction result not found: {extraction_result_id}")
            return
        self._selected_image_file_id = detail.image.id
        self._selected_result_id = detail.selected_result_id
        self.detail_loaded.emit(detail)

    def handle_event(self, event: PipelineEvent) -> None:
        if event.type in {EventType.IMAGE_FINISHED, EventType.RUN_FINISHED}:
            self.refresh(self._status, self._backend, self._model, self._prompt_name, self._run_id)


def _reader_for(cfg: Any) -> GuiReadService:
    return GuiReadService(cfg.database_file)


def _none_for_all(value: str | None) -> str | None:
    if value in (None, "", "all"):
        return None
    return value
