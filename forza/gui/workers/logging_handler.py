from __future__ import annotations

import logging
from collections.abc import Callable


class QtLogHandler(logging.Handler):
    def __init__(self, emit_line: Callable[[str], None]) -> None:
        super().__init__(level=logging.INFO)
        self._emit_line = emit_line

    def emit(self, record: logging.LogRecord) -> None:
        if not record.name.startswith("forza"):
            return
        try:
            self._emit_line(self.format(record))
        except Exception:
            self.handleError(record)


def install_qt_log_handler(
    emit_line: Callable[[str], None],
    *,
    include_name: bool = True,
) -> logging.Handler:
    fmt = "%(asctime)s %(levelname)-8s %(message)s"
    if include_name:
        fmt = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
    handler = QtLogHandler(emit_line)
    handler.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))
    logging.getLogger().addHandler(handler)
    return handler


def remove_qt_log_handler(handler: logging.Handler | None) -> None:
    if handler is None:
        return
    logging.getLogger().removeHandler(handler)
    handler.close()
