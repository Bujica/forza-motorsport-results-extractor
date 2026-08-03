from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

from ...config import AppConfig
from ...events import EventType, PipelineEvent
from ...application.gui_read_service import GuiLap, GuiReadService, GuiReviewCase
from ...application.gui_write_service import GuiWriteService, ReviewDecisionTargetNotFound
from ..config_state import ConfigChangeSet
from ..workers.review_queue_worker import ReviewQueueWorker

_log = logging.getLogger("forza")


# Statuses that are considered "resolved" for filter purposes.
# ``auto_resolved`` is set by the system when it detects that the underlying
# data condition that triggered a review case no longer exists (e.g. after a
# Rebuild).  From the user's perspective it is a resolved case and should
# appear under the "Resolved" filter tab, not disappear entirely.
_RESOLVED_STATUSES: frozenset[str] = frozenset({"resolved", "auto_resolved"})


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
        # Pass a live provider lambda instead of a frozen string.  The lambda
        # closes over ``self._cfg`` (not the local ``cfg`` variable) so that
        # every write operation — including best-lap recomputes triggered by
        # review decisions — always resolves the gamertag from the *current*
        # config object rather than a snapshot captured at construction time.
        # This prevents stale-gamertag recomputes whenever the config is
        # reloaded in the background without a full writer rebuild.
        self._writer = GuiWriteService(
            cfg.database_file,
            gamertag=lambda: str(getattr(self._cfg, "gamertag", "") or "").strip() or None,
        )
        self._all_cases: list[GuiReviewCase] = []
        self._cases: list[GuiReviewCase] = []
        self._current_case: GuiReviewCase | None = None
        self._status = "open"
        self._reason: str | None = None
        self._outcome: str | None = None
        self._run_id: str | None = None
        self._tracks = self._reader.list_reference_tracks()
        self._loaded = False
        self._reload_thread: QThread | None = None
        self._reload_worker: ReviewQueueWorker | None = None
        self._current_reload_on_done = None
        self._pending_reload_on_done = None

    @property
    def cases(self) -> list[GuiReviewCase]:
        return list(self._cases)

    @property
    def is_reloading(self) -> bool:
        return self._reload_thread is not None and self._reload_thread.isRunning()

    def on_config_changed(self, cfg: AppConfig, changes: ConfigChangeSet) -> None:
        self._cfg = cfg
        if changes.affects("paths.database_file"):
            self._reader.close()
            self._writer.close()
            self._reader = GuiReadService(cfg.database_file)
            self._tracks = self._reader.list_reference_tracks()
            self._writer = GuiWriteService(
                cfg.database_file,
                gamertag=lambda: str(getattr(self._cfg, "gamertag", "") or "").strip() or None,
            )
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
        if self._reload_thread is not None and self._reload_thread.isRunning():
            self._reload_thread.quit()
            if not self._reload_thread.wait(5000):
                _log.warning(
                    "[gui] ReviewController: reload thread did not stop within 5s, forcing terminate()"
                )
                self._reload_thread.terminate()
                self._reload_thread.wait(1000)

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
        self._start_reload(lambda: self._apply_current_filters(select_first=True))

    def _start_reload(self, on_done) -> None:
        if self.is_reloading:
            # Coalesce: only the latest requested follow-up runs once the
            # in-flight fetch completes — the query itself (list_review_queue
            # + list_run_options) never takes request-specific arguments, so
            # there is nothing to lose by dropping the redundant intermediate
            # requests, only their now-stale follow-up actions.
            self._pending_reload_on_done = on_done
            return
        self._reload_thread = QThread(self)
        self._reload_worker = ReviewQueueWorker(database_file=self._cfg.database_file)
        self._reload_worker.moveToThread(self._reload_thread)
        self._current_reload_on_done = on_done
        self._reload_thread.started.connect(self._reload_worker.run)
        self._reload_worker.finished.connect(self._on_reload_finished)
        self._reload_worker.finished.connect(self._reload_thread.quit)
        self._reload_worker.finished.connect(self._reload_worker.deleteLater)
        self._reload_thread.finished.connect(self._reload_thread.deleteLater)
        self._reload_thread.finished.connect(self._clear_reload_worker_refs)
        self._reload_thread.start()

    def _on_reload_finished(self, result) -> None:
        on_done = self._current_reload_on_done
        self._current_reload_on_done = None
        if not result.ok:
            self.action_failed.emit(result.message)
            return
        self._all_cases = result.all_cases
        self._loaded = True
        self.run_options_changed.emit(result.run_options)
        if on_done is not None:
            on_done()

    def _clear_reload_worker_refs(self) -> None:
        self._reload_thread = None
        self._reload_worker = None
        if self._pending_reload_on_done is not None:
            pending = self._pending_reload_on_done
            self._pending_reload_on_done = None
            self._start_reload(pending)

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
        if self._status and self._status != "all":
            # ``auto_resolved`` is a system-set variant of "resolved": treat it
            # as belonging to the "resolved" bucket so it surfaces under the
            # Resolved filter tab instead of being invisible everywhere except
            # "All".
            case_bucket = "resolved" if case.status in _RESOLVED_STATUSES else case.status
            if case_bucket != self._status:
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

        def on_done() -> None:
            self._apply_current_filters(select_first=False)
            if not self._cases:
                self.queue_empty.emit()
                return

            current_or_next = next((case for case in self._cases if case.id == resolved_case_id), None)
            if current_or_next is None:
                next_index = min(current_index, len(self._cases) - 1)
                current_or_next = self._cases[next_index]
            self.select_case(current_or_next.id)

        self._start_reload(on_done)

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
