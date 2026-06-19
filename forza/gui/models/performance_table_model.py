from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from ...application.performance_service import CarPerformance, ProgressPoint, RivalRecord, TrackRecord


class PerformanceTableModel(QAbstractTableModel):
    HEADERS = ("Item", "Context", "Value", "Detail")

    def __init__(self, rows: list[object] | None = None, parent=None) -> None:
        super().__init__(parent)
        self._rows = rows or []

    def set_rows(self, rows: list[object]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt override
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt override
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return None
        row = self._rows[index.row()]
        values = (row.primary, row.secondary, row.value, row.detail)
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
        self._rows.sort(key=lambda row: _sort_value(row, column), reverse=reverse)
        self.layoutChanged.emit()


class TrackRecordTableModel(QAbstractTableModel):
    HEADERS = (
        "Track",
        "Class",
        "Weather",
        "My best",
        "Rival",
        "Rival gap",
        "Community record",
        "Community gap",
        "Most used car",
        "Dominant car",
        "Sessions",
        "Last raced",
    )

    def __init__(self, records: list[TrackRecord] | None = None, parent=None) -> None:
        super().__init__(parent)
        self._all_records: list[TrackRecord] = list(records or [])
        self._records: list[TrackRecord] = list(self._all_records)
        self._track_filter: str | None = None
        self._class_filter: str | None = None
        self._weather_filter: str | None = None

    def set_records(self, records: list[TrackRecord]) -> None:
        self.beginResetModel()
        self._all_records = list(records)
        self._records = self._filtered_records()
        self.endResetModel()

    def set_filters(
        self,
        *,
        track: str | None = None,
        race_class: str | None = None,
        weather: str | None = None,
    ) -> None:
        self.beginResetModel()
        self._track_filter = _blank_to_none(track)
        self._class_filter = _blank_to_none(race_class)
        self._weather_filter = _blank_to_none(weather)
        self._records = self._filtered_records()
        self.endResetModel()

    def record_at(self, row: int) -> TrackRecord | None:
        if 0 <= row < len(self._records):
            return self._records[row]
        return None

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt override
        return 0 if parent.isValid() else len(self._records)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._records):
            return None
        record = self._records[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return _display_value(record, index.column())
        if role == Qt.ItemDataRole.ToolTipRole:
            return _tooltip_value(record, index.column())
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in {5, 7, 10}:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        return None

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder) -> None:  # noqa: N802
        reverse = order == Qt.SortOrder.DescendingOrder
        self.layoutAboutToBeChanged.emit()
        self._records.sort(key=_sort_key_for_column(column), reverse=reverse)
        self.layoutChanged.emit()

    def _filtered_records(self) -> list[TrackRecord]:
        records = list(self._all_records)
        if self._track_filter is not None:
            records = [record for record in records if record.track == self._track_filter]
        if self._class_filter is not None:
            records = [record for record in records if record.race_class == self._class_filter]
        if self._weather_filter is not None:
            records = [record for record in records if record.weather == self._weather_filter]
        return records


class CarPerformanceTableModel(QAbstractTableModel):
    HEADERS = ("Car", "Usage", "Player laps", "Wins", "Best", "Gap", "Best driver")

    def __init__(self, rows: list[CarPerformance] | None = None, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[CarPerformance] = list(rows or [])

    def set_rows(self, rows: list[CarPerformance]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            values = (
                row.car,
                str(row.usage_count),
                str(row.player_usage_count),
                str(row.session_wins),
                row.best_display or "—",
                _gap_value(row.gap_to_combo_best_ms),
                row.best_driver or "—",
            )
            return values[index.column()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{row.track} · {row.race_class} · {row.weather}"
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in {1, 2, 3, 5}:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        return None

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder) -> None:  # noqa: N802
        reverse = order == Qt.SortOrder.DescendingOrder
        sorters: tuple[Callable[[CarPerformance], Any], ...] = (
            lambda row: row.car.lower(),
            lambda row: row.usage_count,
            lambda row: row.player_usage_count,
            lambda row: row.session_wins,
            lambda row: _none_high(row.best_ms),
            lambda row: _none_high(row.gap_to_combo_best_ms),
            lambda row: (row.best_driver or "").lower(),
        )
        self.layoutAboutToBeChanged.emit()
        self._rows.sort(key=sorters[column] if 0 <= column < len(sorters) else sorters[0], reverse=reverse)
        self.layoutChanged.emit()


class ProgressTableModel(QAbstractTableModel):
    HEADERS = ("Date", "Lap", "Delta", "Car", "Source")

    def __init__(self, rows: list[ProgressPoint] | None = None, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[ProgressPoint] = list(rows or [])
        self._best_ms: int | None = None

    def set_rows(self, rows: list[ProgressPoint], *, best_ms: int | None = None) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self._best_ms = best_ms
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            delta = row.lap_ms - self._best_ms if self._best_ms is not None else None
            values = (
                _date_display(row.race_date),
                row.lap_display,
                _gap_value(delta),
                row.car,
                row.session_source,
            )
            return values[index.column()]
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in {2}:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        return None


class RivalTableModel(QAbstractTableModel):
    HEADERS = ("Driver", "Combos", "Tracks", "Their best", "My best", "Usually faster")

    def __init__(self, rows: list[RivalRecord] | None = None, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[RivalRecord] = list(rows or [])

    def set_rows(self, rows: list[RivalRecord]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            values = (
                row.driver,
                str(row.sessions_shared),
                str(len(row.tracks_shared)),
                _duration_from_ms(row.their_best_ms),
                _duration_from_ms(row.my_best_in_common_ms),
                "yes" if row.usually_faster else "no",
            )
            return values[index.column()]
        if role == Qt.ItemDataRole.ToolTipRole and index.column() == 2:
            return ", ".join(row.tracks_shared) or "—"
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in {1, 2}:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        return None

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder) -> None:  # noqa: N802
        reverse = order == Qt.SortOrder.DescendingOrder
        sorters: tuple[Callable[[RivalRecord], Any], ...] = (
            lambda row: row.driver.lower(),
            lambda row: row.sessions_shared,
            lambda row: len(row.tracks_shared),
            lambda row: _none_high(row.their_best_ms),
            lambda row: _none_high(row.my_best_in_common_ms),
            lambda row: row.usually_faster,
        )
        self.layoutAboutToBeChanged.emit()
        self._rows.sort(key=sorters[column] if 0 <= column < len(sorters) else sorters[0], reverse=reverse)
        self.layoutChanged.emit()


def _display_value(record: TrackRecord, column: int) -> str:
    values: tuple[Callable[[TrackRecord], str], ...] = (
        lambda row: row.track,
        lambda row: row.race_class,
        lambda row: row.weather,
        lambda row: row.my_best_display or "—",
        _rival_display,
        lambda row: _gap_value(row.gap_to_rival_ms, getattr(row, "gap_to_rival_pct", None)),
        _community_display,
        lambda row: _gap_value(row.gap_to_community_ms, getattr(row, "gap_to_community_pct", None)),
        _most_used_display,
        _dominant_display,
        lambda row: str(row.sessions_raced),
        lambda row: _date_display(row.last_raced),
    )
    if 0 <= column < len(values):
        return values[column](record)
    return ""


def _tooltip_value(record: TrackRecord, column: int) -> str:
    if column == 3:
        return f"{record.my_best_car or '—'} · {record.my_best_date or 'no date'}"
    if column == 4:
        if record.rival_best_display is None:
            return "No rival in shared player sessions for this track/class/weather."
        return f"{record.rival_best_driver or '—'} · {record.rival_best_car or '—'}"
    if column == 6:
        return _community_tooltip(record)
    if column == 8:
        row = _car_row(record, record.most_used_car)
        if row is None:
            return "No car usage data."
        return f"{row.usage_count} lap(s), {row.player_usage_count} player lap(s), best {row.best_display or '—'}"
    if column == 9:
        row = _car_row(record, record.dominant_car)
        if row is None:
            return "No car dominance data."
        return f"{row.session_wins} session win(s), best {row.best_display or '—'} by {row.best_driver or '—'}"
    return _display_value(record, column)


def _sort_key_for_column(column: int):
    sorters: tuple[Callable[[TrackRecord], Any], ...] = (
        lambda row: row.track.lower(),
        lambda row: row.race_class.lower(),
        lambda row: row.weather.lower(),
        lambda row: _none_high(row.my_best_ms),
        lambda row: (row.rival_best_driver or "").lower(),
        lambda row: _none_high_abs_float(getattr(row, "gap_to_rival_pct", None)),
        lambda row: _community_sort_key(row),
        lambda row: _none_high_abs_float(getattr(row, "gap_to_community_pct", None)),
        lambda row: _car_usage_sort_key(row),
        lambda row: _dominant_car_sort_key(row),
        lambda row: row.sessions_raced,
        lambda row: _date_sort_key(row.last_raced),
    )
    if 0 <= column < len(sorters):
        return sorters[column]
    return lambda row: row.track.lower()


def _rival_display(record: TrackRecord) -> str:
    if record.rival_best_display is None:
        return "—"
    return f"{record.rival_best_driver or '—'} · {record.rival_best_display}"


def _community_display(record: TrackRecord) -> str:
    if str(record.weather).lower() != "dry":
        return "not comparable"
    if str(record.race_class).upper() == "TCR":
        return "no TCR record"
    if record.community_display is None:
        return "no data"
    return record.community_display


def _community_tooltip(record: TrackRecord) -> str:
    if str(record.weather).lower() != "dry":
        return "Best Laps community/external records are dry-only."
    if str(record.race_class).upper() == "TCR":
        return "Best Laps community/external records do not include TCR."
    if record.community_display is None:
        return "No active Best Laps community/external record for this dry non-TCR combo."
    return f"{record.community_driver or '—'} · {record.community_car or '—'}"


def _most_used_display(record: TrackRecord) -> str:
    row = _car_row(record, record.most_used_car)
    if row is not None:
        return f"{row.car} ({row.usage_count})"
    return record.most_used_car or "—"


def _dominant_display(record: TrackRecord) -> str:
    row = _car_row(record, record.dominant_car)
    if row is not None:
        return f"{row.car} ({row.session_wins} win{'s' if row.session_wins != 1 else ''})"
    return record.dominant_car or "—"


def _car_usage_sort_key(record: TrackRecord) -> tuple[int, int, int, str]:
    row = _car_row(record, record.most_used_car)
    if row is None:
        return (0, 0, 10**12, "")
    best_ms = row.best_ms if row.best_ms is not None else 10**12
    return (-row.usage_count, -row.player_usage_count, best_ms, row.car.lower())


def _dominant_car_sort_key(record: TrackRecord) -> tuple[int, int, int, str]:
    row = _car_row(record, record.dominant_car)
    if row is None:
        return (0, 10**12, 0, "")
    best_ms = row.best_ms if row.best_ms is not None else 10**12
    return (-row.session_wins, best_ms, -row.usage_count, row.car.lower())


def _car_row(record: TrackRecord, car: str | None):
    if not car:
        return None
    for row in record.car_performance:
        if row.car == car:
            return row
    return None


def _gap_value(ms: int | None, pct: float | None = None) -> str:
    if ms is None:
        return "—"
    sign = "+" if ms > 0 else ""
    seconds = f"{sign}{ms / 1000:.3f}s"
    if pct is None:
        return seconds
    pct_sign = "+" if pct > 0 else ""
    return f"{seconds} ({pct_sign}{pct:.2f}%)"


def _duration_from_ms(ms: int | None) -> str:
    if ms is None:
        return "—"
    minutes, remainder = divmod(int(ms), 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{minutes}:{seconds:02d}.{millis:03d}"


def _date_display(value: date | None) -> str:
    return value.isoformat() if value is not None else "—"


def _community_sort_key(record: TrackRecord) -> tuple[int, int]:
    if str(record.weather).lower() != "dry":
        return (2, 0)
    if str(record.race_class).upper() == "TCR":
        return (3, 0)
    if record.community_ms is None:
        return (1, 0)
    return (0, record.community_ms)


def _date_sort_key(value: date | None) -> tuple[int, str]:
    if value is None:
        return (1, "")
    return (0, value.isoformat())


def _none_high(value: int | None) -> int:
    return value if value is not None else 10**12


def _none_high_abs_float(value: float | None) -> float:
    return abs(value) if value is not None else float("inf")


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = str(value)
    return None if value in {"", "All"} else value


def _sort_value(row, column: int) -> str:
    values = (row.primary, row.secondary, row.value, row.detail)
    return str(values[column]).lower()
