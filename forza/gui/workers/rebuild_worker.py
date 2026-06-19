from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from ...logging_setup import setup_logging

from ...application import DatabaseService, RebuildService
from .logging_handler import install_qt_log_handler, remove_qt_log_handler


@dataclass(frozen=True)
class RebuildWorkerResult:
    ok: bool
    pdf_path: Path | None = None
    review_cases: int = 0
    message: str = ""


class RebuildWorker(QObject):
    """Regenerate relational derived state outside the GUI thread."""

    log_line = Signal(str)
    finished = Signal(object)

    def __init__(
        self,
        *,
        cfg: Any,
        debug: bool = False,
        event_sink: Callable | None = None,
    ) -> None:
        super().__init__()
        self._cfg = cfg
        self._debug = debug
        self._event_sink = event_sink
        self._log_handler: logging.Handler | None = None

    @Slot()
    def run(self) -> None:
        try:
            result = self._rebuild()
        except Exception as exc:  # pragma: no cover - defensive boundary
            logging.getLogger("forza").exception("GUI rebuild worker failed")
            result = RebuildWorkerResult(ok=False, message=str(exc))
        finally:
            self._remove_log_handler()
        self.finished.emit(result)

    def _rebuild(self) -> RebuildWorkerResult:
        setup_logging(self._cfg.log_file, debug=self._debug)
        self._install_log_handler()
        log = logging.getLogger("forza")
        with DatabaseService(self._cfg.database_file) as database:
            refs = database.load_reference_data()
        service = RebuildService(event_sink=self._event_sink)
        log.info("Rebuild: regenerating relational derived state from SQLite; no model calls")
        review_cases = service.rebuild_outputs(self._cfg, refs, log)
        return RebuildWorkerResult(
            ok=True,
            pdf_path=None,
            review_cases=len(review_cases or []),
            message=f"Derived state rebuilt; review cases: {len(review_cases or [])}",
        )

    def _install_log_handler(self) -> None:
        self._log_handler = install_qt_log_handler(self.log_line.emit)

    def _remove_log_handler(self) -> None:
        remove_qt_log_handler(self._log_handler)
        self._log_handler = None
