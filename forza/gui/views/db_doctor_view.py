from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..widgets.card import make_card
from ..widgets.status_badge import StatusBadge


_RESULT_BG = {
    "FAIL": QColor(0x48, 0x18, 0x18),
    "WARN": QColor(0x4A, 0x3A, 0x12),
    "PASS": QColor(0x18, 0x3A, 0x24),
}
_RESULT_FG = {
    "FAIL": QColor(0xFF, 0xB4, 0xB4),
    "WARN": QColor(0xFF, 0xDF, 0x8A),
    "PASS": QColor(0xA8, 0xE8, 0xB0),
}
_BADGE_KIND = {
    "FAIL": "danger",
    "WARN": "warning",
    "PASS": "success",
}


class DbDoctorView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(self._build_header())
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Result", "Count", "Check", "Description"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self.table, 1)

    def _build_header(self) -> QFrame:
        card = make_card()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        self.title = QLabel("Database Doctor")
        self.title.setObjectName("cardTitle")
        self.badge = StatusBadge()
        self.summary = QLabel("Not checked")
        self.summary.setObjectName("mutedLabel")
        self.refresh_button = QPushButton("Run checks")
        layout.addWidget(self.title)
        layout.addWidget(self.badge)
        layout.addWidget(self.summary, 1)
        layout.addWidget(self.refresh_button)
        return card

    def show_report(self, report) -> None:
        errors = [check for check in report.checks if check.severity == "error" and not check.ok]
        warnings = [check for check in report.checks if check.severity == "warning" and not check.ok]
        passing = [check for check in report.checks if check.ok]
        overall = _overall_result(errors=errors, warnings=warnings, ok=report.ok)

        self.badge.set_status(overall, kind=_BADGE_KIND[overall])
        self.summary.setText(
            f"{report.database_file} · schema={report.schema_state} · "
            f"{len(errors)} error, {len(warnings)} warning, {len(passing)} passed"
        )

        self.table.setRowCount(0)
        for check in report.checks:
            row = self.table.rowCount()
            self.table.insertRow(row)
            result = _result_label(check)
            values = [result, str(check.count), check.key, check.detail]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setBackground(_RESULT_BG[result])
                    item.setForeground(_RESULT_FG[result])
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()

    def show_error(self, message: str) -> None:
        self.badge.set_status("FAIL", kind="danger")
        self.summary.setText(message)
        self.table.setRowCount(0)


def _overall_result(*, errors: list, warnings: list, ok: bool) -> str:
    if not ok or errors:
        return "FAIL"
    if warnings:
        return "WARN"
    return "PASS"


def _result_label(check) -> str:
    if check.ok:
        return "PASS"
    if check.severity == "warning":
        return "WARN"
    return "FAIL"
