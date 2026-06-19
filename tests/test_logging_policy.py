from __future__ import annotations

import logging
from pathlib import Path

from forza.gui.workers.logging_handler import QtLogHandler


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_qt_log_handler_only_emits_for_forza_loggers() -> None:
    lines: list[str] = []
    handler = QtLogHandler(lines.append)
    handler.setFormatter(logging.Formatter("%(name)s:%(message)s"))

    handler.emit(logging.LogRecord("alembic.runtime.migration", logging.INFO, "", 1, "hidden", (), None))
    handler.emit(logging.LogRecord("forza.application.run_service", logging.INFO, "", 1, "shown", (), None))

    assert lines == ["forza.application.run_service:shown"]


def test_logging_setup_silences_noisy_migration_loggers() -> None:
    source = _source("forza/logging_setup.py")

    assert '"alembic"' in source
    assert '"alembic.runtime.migration"' in source
    assert '"sqlalchemy.engine"' in source
    assert "setLevel(logging.WARNING)" in source


def test_visible_log_formatter_does_not_append_high_volume_image_events() -> None:
    source = _source("forza/gui/views/logs_view.py")

    assert 'event.type in {"image_started", "image_finished", "batch_started", "batch_finished"}' in source
    assert "return" in source.split('event.type in {"image_started", "image_finished", "batch_started", "batch_finished"}', 1)[1].split("pieces = [event.type]", 1)[0]
    process_source = _source("forza/gui/views/process_view.py")
    assert "format_runtime_event(event)" in process_source


def test_visible_log_formatter_hides_file_hash_from_event_payload() -> None:
    source = _source("forza/gui/views/logs_view.py")

    assert 'if k not in {"file_hash"}' in source


def test_clear_log_truncates_current_file_tab() -> None:
    source = _source("forza/gui/views/logs_view.py")

    assert "def _clear_file" in source
    assert "path.write_text(\"\", encoding=\"utf-8\")" in source
    assert "_errors_log_path(self._cfg.log_file)" in source
    assert "QMessageBox.question" in source
    assert "_flush_file_handlers()" in source
