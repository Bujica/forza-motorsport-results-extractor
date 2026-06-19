from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont


@dataclass(frozen=True)
class _GroupRow:
    title: str


class SettingsTableModel(QAbstractTableModel):
    HEADERS = ("Field", "Value", "Status")
    value_changed = Signal(str, str)

    def __init__(self, rows: list[object] | None = None, parent=None) -> None:
        super().__init__(parent)
        self._rows = rows or []

    def set_rows(self, rows: list[object]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def set_sections(self, sections: list[tuple[str, list[object]]]) -> None:
        rows: list[object] = []
        for title, section_rows in sections:
            rows.append(_GroupRow(title))
            rows.extend(section_rows)
        self.set_rows(rows)

    def group_rows(self) -> list[int]:
        return [index for index, row in enumerate(self._rows) if isinstance(row, _GroupRow)]

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt override
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt override
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        if isinstance(row, _GroupRow):
            if role == Qt.ItemDataRole.DisplayRole:
                return row.title if index.column() == 0 else ""
            if role == Qt.ItemDataRole.FontRole:
                font = QFont()
                font.setBold(True)
                return font
            if role == Qt.ItemDataRole.BackgroundRole:
                return QBrush(QColor("#F4F6F8"))
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole, Qt.ItemDataRole.ToolTipRole):
            values = (row.name, row.value, row.status)
            return str(values[index.column()])
        if role == Qt.ItemDataRole.UserRole:
            return getattr(row, "editor", "text")
        if role == Qt.ItemDataRole.UserRole + 1:
            return tuple(getattr(row, "options", ()))
        return None

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        if role != Qt.ItemDataRole.EditRole or not index.isValid() or index.column() != 1:
            return False
        row = self._rows[index.row()]
        if isinstance(row, _GroupRow):
            return False
        if not getattr(row, "editable", False):
            return False
        new_value = _normalise_value(value)
        if new_value == row.value:
            return False
        self.value_changed.emit(row.key, new_value)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole])
        return True

    def flags(self, index: QModelIndex):
        base = super().flags(index)
        if not index.isValid():
            return base
        row = self._rows[index.row()]
        if isinstance(row, _GroupRow):
            return Qt.ItemFlag.ItemIsEnabled
        if index.column() == 1 and getattr(row, "editable", False):
            return base | Qt.ItemFlag.ItemIsEditable
        return base

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        return None


def _normalise_value(value) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    return str(value)
