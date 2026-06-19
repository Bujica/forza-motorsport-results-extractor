from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from ...application.gui_read_service import GuiImageDebugCase


class ImageDebugTableModel(QAbstractTableModel):
    HEADERS = ("Image", "Race Date", "File", "Process", "Best", "Latest", "Run", "Model", "Attempts", "Laps", "Reviews")

    def __init__(self, cases: list[GuiImageDebugCase] | None = None, parent=None) -> None:
        super().__init__(parent)
        self._cases = cases or []

    def set_cases(self, cases: list[GuiImageDebugCase]) -> None:
        self.beginResetModel()
        self._cases = list(cases)
        self.endResetModel()

    def case_at(self, row: int) -> GuiImageDebugCase | None:
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
            case.image_name,
            _date_label(case.race_date),
            case.file_status,
            case.processing_status,
            case.best_lap_status,
            case.latest_result_status or "—",
            case.run_label or "—",
            case.model or "—",
            case.attempt_count,
            case.lap_count,
            case.review_count,
        )
        return str(values[index.column()])

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        return None

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder) -> None:  # noqa: N802
        reverse = order == Qt.SortOrder.DescendingOrder
        self.layoutAboutToBeChanged.emit()
        self._cases.sort(key=lambda case: _sort_value(case, column), reverse=reverse)
        self.layoutChanged.emit()


def _sort_value(case: GuiImageDebugCase, column: int):
    values = (
        case.image_name,
        _date_label(case.race_date),
        case.file_status,
        case.processing_status,
        case.best_lap_status,
        case.latest_result_status or "",
        case.run_label or "",
        case.model or "",
        case.attempt_count,
        case.lap_count,
        case.review_count,
    )
    value = values[column]
    return value.lower() if isinstance(value, str) else value


def _date_label(value) -> str:
    if value is None:
        return "—"
    date = getattr(value, "date", None)
    if callable(date):
        return date().isoformat()
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return str(value)
