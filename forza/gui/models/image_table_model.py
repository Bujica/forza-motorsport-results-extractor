from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from ...schemas import ImageFile


class ImageTableModel(QAbstractTableModel):
    HEADERS = ("Name", "Race Date", "Semantic", "File", "Duplicate", "Process", "Best laps")

    def __init__(self, images: list[ImageFile] | None = None, parent=None) -> None:
        super().__init__(parent)
        self._images = images or []

    def set_images(self, images: list[ImageFile]) -> None:
        self.beginResetModel()
        self._images = list(images)
        self.endResetModel()

    def image_at(self, row: int) -> ImageFile | None:
        if row < 0 or row >= len(self._images):
            return None
        return self._images[row]

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt override
        return 0 if parent.isValid() else len(self._images)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt override
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.ToolTipRole:
            if index.column() == 1:
                return "Race date derived from race metadata, not the file modification date."
            return None
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        image = self._images[index.row()]
        values = (
            image.current_name or "Image",
            _race_date_label(image),
            image.semantic_name or "—",
            image.file_status,
            _duplicate_label(image, self._images),
            _processing_label(image.processing_status),
            image.best_lap_status,
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
        self._images.sort(key=lambda image: _sort_value(image, column), reverse=reverse)
        self.layoutChanged.emit()


def _sort_value(image: ImageFile, column: int) -> str:
    values = (
        image.current_name or "Image",
        _race_date_sort_value(image),
        image.semantic_name or "",
        image.file_status,
        "duplicate" if image.duplicate_of_image_file_id else "",
        _processing_label(image.processing_status),
        image.best_lap_status,
    )
    return str(values[column]).lower()


def _race_date_label(image: ImageFile) -> str:
    value = _race_date_value(image)
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value) or "—"


def _race_date_sort_value(image: ImageFile) -> str:
    value = _race_date_value(image)
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _race_date_value(image: ImageFile):
    race_date = getattr(image, "race_date", None)
    if race_date is not None:
        return race_date
    race_datetime = getattr(image, "race_datetime", None)
    if race_datetime is not None:
        return race_datetime
    return None


def _duplicate_label(image: ImageFile, images: list[ImageFile]) -> str:
    if image.duplicate_of_image_file_id:
        return "Duplicate"
    if any(other.duplicate_of_image_file_id == image.id for other in images):
        return "Canonical"
    return ""


def _processing_label(status) -> str:
    return {
        "unprocessed": "Unprocessed",
        "processing": "Processing",
        "processed_ok": "OK",
        "processed_error": "Error",
        "cancelled": "Cancelled",
        "skipped": "Skipped",
    }.get(str(status), str(status))
