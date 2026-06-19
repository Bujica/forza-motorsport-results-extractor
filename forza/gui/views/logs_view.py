from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices, QTextCharFormat, QTextCursor, QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...config import AppConfig
from ..config_state import ConfigChangeSet
from ..widgets.card import make_card, make_card_title
from ..widgets.event_log import EventLog


def format_runtime_event(event: Any) -> str | None:
    if event.type in {"image_started", "image_finished", "batch_started", "batch_finished"}:
        return None
    ts = datetime.now().strftime("%H:%M:%S")
    pieces = [event.type]
    if event.run_id:
        pieces.append(f"run={event.run_id}")
    if event.message:
        pieces.append(event.message)
    elif event.data:
        payload = ", ".join(
            f"{k}={v}"
            for k, v in sorted(event.data.items())
            if k not in {"file_hash"}
        )
        pieces.append(payload)
    return f"[{ts}] [event] " + " · ".join(pieces)


class LogsView(QWidget):
    def __init__(self, *, cfg, parent=None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._build_ui()

    def on_config_changed(self, cfg: AppConfig, changes: ConfigChangeSet) -> None:
        self._cfg = cfg
        if changes.affects("paths.log_file"):
            self.reload_files()

    # ── Build ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        root.addWidget(self._build_log_card(), 1)

    def _build_log_card(self) -> QFrame:
        card = make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(10)

        # Header row
        header = QHBoxLayout()
        header.addWidget(make_card_title("Technical Logs"))
        header.addStretch(1)
        self.clear_button = QPushButton("Clear tab")
        self.clear_button.clicked.connect(self.clear_current_tab)
        self.open_logs_button = QPushButton("Open log folder")
        self.open_logs_button.clicked.connect(self.open_logs)
        for btn in (self.clear_button, self.open_logs_button):
            header.addWidget(btn)
        layout.addLayout(header)

        # Search bar (acts on whichever tab is active)
        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search in current tab… (Enter / Shift+Enter)")
        self.search_box.returnPressed.connect(self._search_next)
        search_row.addWidget(self.search_box, 1)
        prev_btn = QPushButton("↑ Prev")
        prev_btn.clicked.connect(self._search_prev)
        next_btn = QPushButton("↓ Next")
        next_btn.clicked.connect(self._search_next)
        search_row.addWidget(prev_btn)
        search_row.addWidget(next_btn)
        self._search_result_label = QLabel("")
        self._search_result_label.setObjectName("mutedLabel")
        search_row.addWidget(self._search_result_label)
        layout.addLayout(search_row)

        # Tabs — focused on file inspection; no streaming tab
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.app_log = EventLog()
        self.error_log = EventLog()

        self.app_log.setPlaceholderText("Application log entries will appear here.")
        self.error_log.setPlaceholderText("Error log entries will appear here.")

        self.tabs.addTab(self.app_log,   "Application Log")
        self.tabs.addTab(self.error_log, "Errors")

        layout.addWidget(self.tabs, 1)

        # Load files immediately on construction
        self.reload_files()
        return card

    # ── Public API ─────────────────────────────────────────────────────────

    def append_event(self, event: Any) -> None:
        """Runtime events from the pipeline — formatted with timestamp, no dedicated tab."""
        # Only forward to the Application Log so investigators can correlate
        line = format_runtime_event(event)
        if line is not None:
            self.app_log.append_line(line)

    def reload_files(self) -> None:
        self._load_file(self.app_log, self._cfg.log_file)
        self._load_file(self.error_log, _errors_log_path(self._cfg.log_file))

    def clear_current_tab(self) -> None:
        current = self.tabs.currentWidget()
        if current is self.app_log:
            self._clear_file(self._cfg.log_file, self.app_log)
        elif current is self.error_log:
            self._clear_file(_errors_log_path(self._cfg.log_file), self.error_log)
        elif isinstance(current, EventLog):
            current.clear_log()

    def open_logs(self) -> None:
        _open_path(self._cfg.log_file.parent)

    # ── Search ─────────────────────────────────────────────────────────────

    def _current_log(self) -> EventLog | None:
        w = self.tabs.currentWidget()
        return w if isinstance(w, EventLog) else None

    def _search_next(self) -> None:
        self._do_search(forward=True)

    def _search_prev(self) -> None:
        self._do_search(forward=False)

    def _do_search(self, *, forward: bool) -> None:
        log = self._current_log()
        if log is None:
            return
        query = self.search_box.text().strip()
        if not query:
            self._search_result_label.setText("")
            return
        from PySide6.QtGui import QTextDocument
        flags = QTextDocument.FindFlag(0)
        if not forward:
            flags |= QTextDocument.FindFlag.FindBackward
        found = log.find(query, flags)
        if not found:
            # Wrap around
            cursor = log.textCursor()
            if forward:
                cursor.movePosition(QTextCursor.MoveOperation.Start)
            else:
                cursor.movePosition(QTextCursor.MoveOperation.End)
            log.setTextCursor(cursor)
            found = log.find(query, flags)
        self._search_result_label.setText("" if found else "Not found")

    def _on_tab_changed(self, _index: int) -> None:
        self._search_result_label.setText("")

    # ── File helpers ───────────────────────────────────────────────────────

    def _load_file(self, target: EventLog, path: Path) -> None:
        if not path.exists():
            target.setPlaceholderText(f"Log file not found: {path}")
            target.clear_log()
            return
        try:
            target.setPlainText(path.read_text(encoding="utf-8", errors="replace"))
            # Scroll to the end so the most recent entries are visible
            cursor = target.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            target.setTextCursor(cursor)
        except OSError as exc:
            target.setPlainText(f"Could not read log file: {path}\n{exc}")

    def _clear_file(self, path: Path, target: EventLog) -> None:
        if not _confirm_clear_file(self, path):
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        _truncate_log_file(path)
        target.clear_log()


# ── Module-level helpers ───────────────────────────────────────────────────────
def _errors_log_path(log_file: Path) -> Path:
    return log_file.parent / f"{log_file.stem}_errors{log_file.suffix}"


def _open_path(path: Path) -> None:
    if path.exists():
        QDesktopServices.openUrl(path.resolve().as_uri())


def _flush_file_handlers() -> None:
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.FileHandler):
            handler.flush()


def _truncate_log_file(path: Path) -> None:
    resolved = str(path.resolve())
    handled = False
    for handler in logging.getLogger().handlers:
        if not isinstance(handler, logging.FileHandler):
            continue
        if str(Path(handler.baseFilename).resolve()) != resolved:
            continue
        handler.acquire()
        try:
            if handler.stream is not None:
                handler.stream.seek(0)
                handler.stream.truncate(0)
                handler.stream.flush()
                handled = True
        finally:
            handler.release()
    if not handled:
        path.write_text("", encoding="utf-8")


def _confirm_clear_file(parent, path: Path) -> bool:
    answer = QMessageBox.question(
        parent,
        "Clear log file",
        f"Clear {path}? This cannot be undone.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes


# Cosmetic helper if future styling is added
def _highlight_format() -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setBackground(QColor("#2F80ED"))
    fmt.setForeground(QColor("white"))
    return fmt
