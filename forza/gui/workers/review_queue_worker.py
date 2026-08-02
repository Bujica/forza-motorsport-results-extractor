from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from ...application.gui_read_service import GuiReadService, GuiReviewCase


@dataclass(frozen=True)
class ReviewQueueWorkerResult:
    ok: bool
    all_cases: list[GuiReviewCase] | None = None
    run_options: list[object] | None = None
    message: str = ""


class ReviewQueueWorker(QObject):
    finished = Signal(object)

    def __init__(self, *, database_file: Any) -> None:
        super().__init__()
        self._database_file = database_file

    @Slot()
    def run(self) -> None:
        # A fresh, worker-thread-local reader — never share the controller's
        # own GuiReadService/session across threads.
        reader = GuiReadService(self._database_file)
        try:
            all_cases = reader.list_review_queue(status="all")
            run_options = reader.list_run_options()
            payload = ReviewQueueWorkerResult(ok=True, all_cases=all_cases, run_options=run_options)
        except Exception as exc:  # pragma: no cover - GUI boundary
            payload = ReviewQueueWorkerResult(ok=False, message=str(exc))
        finally:
            reader.close()
        self.finished.emit(payload)
