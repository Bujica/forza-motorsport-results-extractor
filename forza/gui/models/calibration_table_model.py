from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


class CalibrationTableModel(QAbstractTableModel):
    HEADERS = ("Flag", "Status", "Image", "Best", "File", "Reason")

    def __init__(self, candidates: list[object] | None = None, parent=None) -> None:
        super().__init__(parent)
        self._candidates = candidates or []

    def set_candidates(self, candidates: list[object]) -> None:
        self.beginResetModel()
        self._candidates = list(candidates)
        self.endResetModel()

    def candidate_at(self, row: int):
        if row < 0 or row >= len(self._candidates):
            return None
        return self._candidates[row]

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt override
        return 0 if parent.isValid() else len(self._candidates)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt override
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return None
        item = self._candidates[index.row()]
        image = item.image
        values = (
            item.flag.flag,
            item.flag.status,
            image.current_name or "Image",
            image.best_lap_status,
            image.file_status,
            item.flag.reason or "—",
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
        self._candidates.sort(key=lambda item: _sort_value(item, column), reverse=reverse)
        self.layoutChanged.emit()


def _sort_value(item, column: int) -> str:
    image = item.image
    values = (
        item.flag.flag,
        item.flag.status,
        image.current_name or "Image",
        image.best_lap_status,
        image.file_status,
        item.flag.reason or "",
    )
    return str(values[column]).lower()
