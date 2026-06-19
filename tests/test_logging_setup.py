from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

import pytest

from forza.logging_setup import setup_logging


class _CloseErrorHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.close_called = False

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - not used by these tests
        pass

    def close(self) -> None:
        self.close_called = True
        raise RuntimeError("close failed")


@pytest.fixture(autouse=True)
def restore_root_logger_handlers():
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    yield
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        handler.close()
    root.handlers[:] = original_handlers
    root.setLevel(original_level)


def test_setup_logging_creates_rotating_file_handlers_and_console_handler(tmp_path) -> None:
    log_file = tmp_path / "nested" / "forza_debug.log"

    setup_logging(log_file, debug=False)

    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert len(root.handlers) == 3

    app_handler, err_handler, console_handler = root.handlers
    assert isinstance(app_handler, logging.handlers.RotatingFileHandler)
    assert isinstance(err_handler, logging.handlers.RotatingFileHandler)
    assert isinstance(console_handler, logging.StreamHandler)

    assert Path(app_handler.baseFilename) == log_file
    assert Path(err_handler.baseFilename) == tmp_path / "nested" / "forza_debug_errors.log"
    assert app_handler.level == logging.DEBUG
    assert err_handler.level == logging.WARNING
    assert console_handler.level == logging.INFO

    logging.getLogger("forza.test").debug("debug in app only")
    logging.getLogger("forza.test").warning("warning in both files")
    for handler in root.handlers:
        handler.flush()

    assert log_file.exists()
    assert "debug in app only" in log_file.read_text(encoding="utf-8")
    assert "warning in both files" in log_file.read_text(encoding="utf-8")

    errors_log = tmp_path / "nested" / "forza_debug_errors.log"
    assert errors_log.exists()
    errors_text = errors_log.read_text(encoding="utf-8")
    assert "warning in both files" in errors_text
    assert "debug in app only" not in errors_text


def test_setup_logging_debug_mode_sets_console_to_debug(tmp_path) -> None:
    setup_logging(tmp_path / "app.log", debug=True)

    console_handler = logging.getLogger().handlers[2]

    assert console_handler.level == logging.DEBUG


def test_setup_logging_replaces_existing_handlers_and_ignores_close_failure(tmp_path) -> None:
    root = logging.getLogger()
    bad_handler = _CloseErrorHandler()
    root.addHandler(bad_handler)

    setup_logging(tmp_path / "app.log")

    assert bad_handler.close_called is True
    assert bad_handler not in root.handlers
    assert len(root.handlers) == 3


@pytest.mark.parametrize(
    "logger_name",
    [
        "PIL",
        "urllib3",
        "httpx",
        "httpcore",
        "alembic",
        "alembic.runtime.migration",
        "sqlalchemy.engine",
        "sqlalchemy.pool",
    ],
)
def test_setup_logging_silences_noisy_third_party_loggers(tmp_path, logger_name: str) -> None:
    logging.getLogger(logger_name).setLevel(logging.DEBUG)

    setup_logging(tmp_path / "app.log")

    assert logging.getLogger(logger_name).level == logging.WARNING
