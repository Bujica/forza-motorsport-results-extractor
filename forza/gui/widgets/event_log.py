from __future__ import annotations

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QPlainTextEdit


class EventLog(QPlainTextEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setMaximumBlockCount(3000)
        self.setPlaceholderText("Run events and logs will appear here.")

    def append_line(self, line: str) -> None:
        self.appendPlainText(line.rstrip())
        self.moveCursor(QTextCursor.MoveOperation.End)

    def clear_log(self) -> None:
        self.clear()
