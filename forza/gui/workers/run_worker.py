from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from ...events import PipelineEvent
from ...logging_setup import setup_logging

from ...application import DatabaseService, RunControl, RunOptions, RunService
from .logging_handler import install_qt_log_handler, remove_qt_log_handler


@dataclass(frozen=True)
class RunRequest:
    dry_run: bool = False
    force: bool = False
    retry_errors: bool = False
    debug: bool = False
    selected_image_file_ids: tuple[str, ...] | None = None


@dataclass(frozen=True)
class RunWorkerResult:
    status: str
    error: str | None = None


class RunWorker(QObject):
    """Run the processing pipeline outside the GUI thread."""

    log_line = Signal(str)
    finished = Signal(object)

    def __init__(
        self,
        *,
        cfg: Any,
        request: RunRequest,
        event_sink: Callable[[PipelineEvent], None] | None = None,
    ) -> None:
        super().__init__()
        self._cfg = cfg
        self._request = request
        self._event_sink = event_sink
        self._log_handler: logging.Handler | None = None
        self._control = RunControl()

    @Slot()
    def run(self) -> None:
        try:
            status = self._run_pipeline()
        except Exception as exc:  # pragma: no cover - defensive boundary
            logging.getLogger("forza").exception("GUI run worker failed")
            self.finished.emit(RunWorkerResult(status="failed", error=str(exc)))
        else:
            self.finished.emit(RunWorkerResult(status=status))
        finally:
            self._remove_log_handler()

    def request_pause(self) -> None:
        self._control.pause()

    def request_resume(self) -> None:
        self._control.resume()

    def request_cancel(self) -> None:
        self._control.cancel()

    def _run_pipeline(self) -> str:
        setup_logging(self._cfg.log_file, debug=self._request.debug)
        self._install_log_handler()
        log = logging.getLogger("forza")
        with DatabaseService(self._cfg.database_file) as database:
            refs = database.load_reference_data()

        return RunService(event_sink=self._event_sink, run_control=self._control).run(
            self._cfg,
            refs,
            log,
            options=RunOptions(
                dry_run=self._request.dry_run,
                force=self._request.force,
                retry_errors=self._request.retry_errors,
                selected_image_file_ids=self._request.selected_image_file_ids,
            ),
        )

    def _install_log_handler(self) -> None:
        self._log_handler = install_qt_log_handler(self.log_line.emit)

    def _remove_log_handler(self) -> None:
        remove_qt_log_handler(self._log_handler)
        self._log_handler = None
