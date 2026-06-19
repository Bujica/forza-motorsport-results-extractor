from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from ...config import AppConfig
from ...events import EventType, PipelineEvent
from ...application.gui_read_service import GuiLap, GuiReadService, GuiReviewCase
from ...application.gui_write_service import GuiWriteService, ReviewDecisionTargetNotFound
from ..config_state import ConfigChangeSet


class ReviewController(QObject):
    queue_changed = Signal(object)
    filter_options_changed = Signal(object)
    run_options_changed = Signal(object)
    selection_changed = Signal(object, object, object, object)
    action_completed = Signal(str)
    action_failed = Signal(str)
    queue_empty = Signal()

    def __init__(self, *, cfg: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._reader = GuiReadService(cfg.database_file)
        self._writer = GuiWriteService(cfg.database_file, gamertag=getattr(cfg, "gamertag", None))
        self._all_cases: list[GuiReviewCase] = []
        self._cases: list[GuiReviewCase] = []
        self._current_case: GuiReviewCase | None = None
        self._status = "open"
        self._reason: str | None = None
        self._outcome: str | None = None
        self._run_id: str | None = None
        self._tracks = self._reader.list_reference_tracks()
        self._loaded = False

    @property
    def cases(self) -> list[GuiReviewCase]:
        return list(self._cases)

    def on_config_changed(self, cfg: AppConfig, changes: ConfigChangeSet) -> None:
        self._cfg = cfg
        if changes.affects("paths.database_file"):
            self._reader.close()
            self._writer.close()
            self._reader = GuiReadService(cfg.database_file)
            self._tracks = self._reader.list_reference_tracks()
            self._writer = GuiWriteService(cfg.database_file, gamertag=getattr(cfg, "gamertag", None))
            self._all_cases = []
            self._cases = []
            self._current_case = None
            self._loaded = False
            self.queue_changed.emit(self._cases)
            self.filter_options_changed.emit({"reasons": [], "outcomes": []})
            self.run_options_changed.emit([])
            self.selection_changed.emit(None, None, [], None)

    def close(self) -> None:
        self._reader.close()
        self._writer.close()

    def refresh(
        self,
        status: str = "open",
        reason: str | None = None,
        run_id: str | None = None,
        outcome: str | None = None,
    ) -> None:
        self._set_filters(status, reason, run_id, outcome)
        self.reload()

    def reload(self) -> None:
        self._all_cases = self._reader.list_review_queue(status="all")
        self._loaded = True
        self.run_options_changed.emit(self._reader.list_run_options())
        self._apply_current_filters(select_first=True)

    def apply_filters(
        self,
        status: str = "open",
        reason: str | None = None,
        run_id: str | None = None,
        outcome: str | None = None,
    ) -> None:
        self._set_filters(status, reason, run_id, outcome)
        if not self._loaded:
            self.reload()
            return
        self._apply_current_filters(select_first=True)

    def select_case(self, case_id: str) -> None:
        case = next((item for item in self._cases if item.id == case_id), None)
        self._current_case = case
        if case is None:
            self.selection_changed.emit(None, None, [], None)
            return
        image = self._reader.get_image(case.image_file_id) if case.image_file_id else None
        laps: list[GuiLap] = []
        if case.image_file_id:
            laps = self._reader.list_laps(image_file_id=case.image_file_id, run_id=case.run_id)
        preview_path = self._preview_path(case, image)
        self.selection_changed.emit(case, image, laps, preview_path)

    def resolve_current(self) -> None:
        self._set_current_status("resolved")

    def ignore_current(self) -> None:
        self._set_current_status("ignored")

    def reopen_current(self) -> None:
        self._set_current_status("open")

    def confirm_dirty(self) -> None:
        self._apply_decision("dirty", True, "Dirty lap confirmed")

    def mark_clean(self) -> None:
        self._apply_decision("dirty", False, "Lap marked clean")

    def set_track(self, track: str) -> None:
        value = str(track or "").strip()
        if not value or value == "all":
            self.action_failed.emit("Choose a track before applying the correction.")
            return
        self._apply_decision("track", value, "Track corrected")

    def set_weather(self, weather: str) -> None:
        value = str(weather or "").strip()
        if not value or value == "all":
            self.action_failed.emit("Choose a weather value before applying the correction.")
            return
        self._apply_decision("weather", value, "Weather corrected")

    def set_race_class(self, race_class: str) -> None:
        value = str(race_class or "").strip()
        if not value or value == "all":
            self.action_failed.emit("Choose a race class before applying the correction.")
            return
        self._apply_decision("race_class", value, "Class corrected")

    def set_car(self, car: str) -> None:
        value = str(car or "").strip()
        if not value:
            self.action_failed.emit("Enter a car before applying the correction.")
            return
        self._apply_decision("car", value, "Car corrected")

    def set_driver_name(self, driver_name: str) -> None:
        value = str(driver_name or "").strip()
        if not value:
            self.action_failed.emit("Enter a driver name before applying the correction.")
            return
        self._apply_decision("driver", value, "Driver name corrected")

    def select_next(self) -> None:
        self._select_relative(1)

    def select_previous(self) -> None:
        self._select_relative(-1)

    def handle_event(self, event: PipelineEvent) -> None:
        if event.type in {EventType.REVIEW_CASE_CHANGED, EventType.REVIEW_CASES_CREATED, EventType.LAP_RECORD_CORRECTED}:
            self.reload()

    def track_options(self) -> list[str]:
        return list(self._tracks)

    def _set_filters(self, status: str | None, reason: str | None, run_id: str | None, outcome: str | None) -> None:
        self._status = status or "open"
        self._reason = reason or None
        self._outcome = outcome or None
        self._run_id = run_id or None

    def _apply_current_filters(self, *, select_first: bool) -> None:
        self._cases = [case for case in self._all_cases if self._case_matches(case)]
        self.queue_changed.emit(self._cases)
        self.filter_options_changed.emit(self._filter_options())
        if select_first and self._cases:
            self.select_case(self._cases[0].id)
        elif not self._cases:
            self._current_case = None
            self.selection_changed.emit(None, None, [], None)

    def _case_matches(self, case: GuiReviewCase) -> bool:
        if self._status and self._status != "all" and case.status != self._status:
            return False
        if self._reason and self._reason != "all" and case.reason != self._reason:
            return False
        if self._outcome and self._outcome != "all" and case.outcome != self._outcome:
            return False
        if self._run_id and self._run_id != "all" and case.run_id != self._run_id:
            return False
        return True

    def _filter_options(self) -> dict[str, list[str]]:
        return {
            "reasons": sorted({case.reason for case in self._all_cases if case.reason}),
            "outcomes": sorted({case.outcome for case in self._all_cases if case.outcome}),
        }

    def _set_current_status(self, status: str) -> None:
        if self._current_case is None:
            self.action_failed.emit("No case selected.")
            return
        case_id = self._current_case.id
        if status == "resolved":
            result = self._writer.resolve_review_case(case_id)
        elif status == "ignored":
            result = self._writer.ignore_review_case(case_id)
        elif status == "open":
            result = self._writer.reopen_review_case(case_id)
        else:
            self.action_failed.emit(f"Invalid status: {status}")
            return
        if result is None:
            self.action_failed.emit("Case not found in the database.")
            return
        self.action_completed.emit(f"Case {status}: {case_id}")
        self.reload()

    def _apply_decision(self, field: str, value: object, message: str) -> None:
        if self._current_case is None:
            self.action_failed.emit("No case selected.")
            return
        case = self._current_case
        try:
            result = self._writer.resolve_review_case_with_decision(
                case.id,
                lap_record_id=case.lap_record_id,
                decision={"field": field, "value": value},
            )
        except ReviewDecisionTargetNotFound as exc:
            self.action_failed.emit(str(exc))
            return
        if result is None:
            self.action_failed.emit("Case not found in the database.")
            return
        self.action_completed.emit(f"{message}: #{case.case_number or case.id}")
        self._advance_to_next(case.id)

    def _advance_to_next(self, resolved_case_id: str) -> None:
        current_index = next((index for index, case in enumerate(self._cases) if case.id == resolved_case_id), 0)
        self._all_cases = self._reader.list_review_queue(status="all")
        self.run_options_changed.emit(self._reader.list_run_options())
        self._apply_current_filters(select_first=False)
        if not self._cases:
            self.queue_empty.emit()
            return

        current_or_next = next((case for case in self._cases if case.id == resolved_case_id), None)
        if current_or_next is None:
            next_index = min(current_index, len(self._cases) - 1)
            current_or_next = self._cases[next_index]
        self.select_case(current_or_next.id)

    def _select_relative(self, offset: int) -> None:
        if not self._cases:
            return
        current_id = self._current_case.id if self._current_case is not None else None
        current_index = next((index for index, case in enumerate(self._cases) if case.id == current_id), 0)
        next_index = max(0, min(len(self._cases) - 1, current_index + offset))
        self.select_case(self._cases[next_index].id)

    def _preview_path(self, case: GuiReviewCase, image) -> Path | None:
        if image is not None and image.current_path is not None:
            return Path(image.current_path)
        return None
