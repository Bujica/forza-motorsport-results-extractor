from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from ...application.gui_read_service import GuiReviewCase


class ReviewTableModel(QAbstractTableModel):
    HEADERS = ("#", "Outcome", "Reason", "Trigger", "Decision", "Driver", "Lap")

    def __init__(self, cases: list[GuiReviewCase] | None = None, parent=None) -> None:
        super().__init__(parent)
        self._cases = cases or []

    def set_cases(self, cases: list[GuiReviewCase]) -> None:
        self.beginResetModel()
        self._cases = list(cases)
        self.endResetModel()

    def case_at(self, row: int) -> GuiReviewCase | None:
        if row < 0 or row >= len(self._cases):
            return None
        return self._cases[row]

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt override
        return 0 if parent.isValid() else len(self._cases)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt override
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return None
        case = self._cases[index.row()]
        values = (
            case.case_number or "—",
            case.outcome,
            case.reason,
            case.trigger or "—",
            _decision_label(case),
            case.current_driver or case.driver or "—",
            _current_lap_label(case),
        )
        return str(values[index.column()])

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        return None


def _decision_label(case: GuiReviewCase) -> str:
    if case.decision_field and case.corrected_value is not None:
        before = case.model_value if case.model_value is not None else "?"
        return f"{case.decision_field}: {before} -> {case.corrected_value}"
    return "—"


def _current_lap_label(case: GuiReviewCase) -> str:
    lap = case.current_best_lap if case.current_best_lap is not None else case.best_lap
    if not lap:
        return "—"
    if case.current_dirty:
        return f"{lap} dirty"
    return lap
