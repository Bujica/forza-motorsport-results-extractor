from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor, QFont

from ...config import CLASS_COLORS
from ...domain import strip_dirty_symbol


class BestLapsTableModel(QAbstractTableModel):
    HEADERS = (
        "Driver",
        "Car",
        "Best Lap",
        "Weather",
        "Temp",
        "Source",
    )

    def __init__(
        self,
        rows: list[object] | None = None,
        *,
        dirty_lap_symbol: str = "\u2020",
        show_dirty_lap_symbol: bool = True,
        gamertag: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._rows: list[object] = []
        self._display_rows: list[tuple[str, object]] = []
        self._dirty_lap_symbol = dirty_lap_symbol
        self._show_dirty_lap_symbol = show_dirty_lap_symbol
        self._gamertag = gamertag.strip().lower()
        self.set_rows(rows or [])

    def set_rows(self, rows: list[object]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self._display_rows = _group_rows(self._rows)
        self.endResetModel()

    def row_at(self, row: int):
        if row < 0 or row >= len(self._display_rows):
            return None
        kind, value = self._display_rows[row]
        return value if kind == "lap" else None

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt override
        return 0 if parent.isValid() else len(self._display_rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt override
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        kind, row = self._display_rows[index.row()]
        if kind == "group":
            return self._group_data(row, index.column(), role)
        return self._lap_data(row, index.column(), role)

    def _group_data(self, group, column: int, role):
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return f"{group.track} · {group.race_class}"
            if column == len(self.HEADERS) - 1:
                return f"{group.count} lap{'s' if group.count != 1 else ''}"
            return ""
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{group.track} · {group.race_class}"
        if role == Qt.ItemDataRole.BackgroundRole:
            return QBrush(QColor(CLASS_COLORS.get(group.race_class, CLASS_COLORS["Unknown"])))
        if role == Qt.ItemDataRole.ForegroundRole:
            return QBrush(QColor("white"))
        if role == Qt.ItemDataRole.FontRole:
            font = QFont()
            font.setBold(True)
            return font
        return None

    def _lap_data(self, row, column: int, role):
        if role == Qt.ItemDataRole.DisplayRole:
            return str(_lap_values(row, self._dirty_lap_symbol, self._show_dirty_lap_symbol)[column])
        if role == Qt.ItemDataRole.ToolTipRole:
            dirty = "dirty" if row.dirty else "clean"
            source = getattr(row, "source_label", "") or row.source_file
            return f"{row.track} · {row.race_class} · {row.driver} · {row.car} · {dirty} · {source}"
        if role == Qt.ItemDataRole.BackgroundRole:
            if getattr(row, "is_external", False):
                return QBrush(QColor("#D6EAF8"))
            if self._is_player_row(row):
                return QBrush(QColor("#FFF8DC"))
        if role == Qt.ItemDataRole.ForegroundRole and column == 2 and row.dirty:
            return QBrush(QColor("#E74C3C"))
        if role == Qt.ItemDataRole.TextAlignmentRole and column in {2, 3, 4}:
            return Qt.AlignmentFlag.AlignCenter
        return None

    def _is_player_row(self, row) -> bool:
        return bool(self._gamertag and str(row.driver).strip().lower() == self._gamertag)

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        return None


class _GroupRow:
    def __init__(self, track: str, race_class: str, count: int) -> None:
        self.track = track
        self.race_class = race_class
        self.count = count


def _group_rows(rows: list[object]) -> list[tuple[str, object]]:
    display_rows: list[tuple[str, object]] = []
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (row.track, row.race_class)
        counts[key] = counts.get(key, 0) + 1
    current_key: tuple[str, str] | None = None
    for row in rows:
        key = (row.track, row.race_class)
        if key != current_key:
            display_rows.append(("group", _GroupRow(row.track, row.race_class, counts[key])))
            current_key = key
        display_rows.append(("lap", row))
    return display_rows


def _lap_values(row, dirty_lap_symbol: str, show_dirty_lap_symbol: bool) -> tuple[str, str, str, str, str, str]:
    lap = strip_dirty_symbol(str(row.best_lap))
    if row.dirty and show_dirty_lap_symbol:
        lap = f"{lap} {dirty_lap_symbol}"
    temp = "\u2014" if row.temp_f is None else f"{row.temp_f:g}\u00b0F"
    return (
        row.driver,
        row.car,
        lap,
        str(row.weather).title(),
        temp,
        getattr(row, "source_label", "") or row.source_file,
    )

