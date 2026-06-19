from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...schemas import ImageFile
from ..widgets.card import make_card
from ..widgets.image_preview import ImagePreview
from ..widgets.status_badge import StatusBadge


class ImageDetailDialog(QDialog):
    open_debug_requested = Signal(str)
    previous_image_requested = Signal()
    next_image_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Image Details")
        self.resize(1180, 760)
        self._extraction_result_ids: list[str] = []
        self._selected_extraction_result_id: str | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        header = QHBoxLayout()
        self.title = QLabel("Image Details")
        self.title.setObjectName("sectionTitle")
        self.file_status = StatusBadge()
        self.best_status = StatusBadge()
        header.addWidget(self.title, 1)
        header.addWidget(self.file_status)
        header.addWidget(self.best_status)
        root.addLayout(header)

        splitter = QSplitter()
        splitter.addWidget(self._build_preview_panel())
        splitter.addWidget(self._build_detail_tabs())
        splitter.setSizes([520, 620])
        root.addWidget(splitter, 1)

        buttons = QHBoxLayout()
        self.previous_button = QPushButton("← Previous")
        self.previous_button.clicked.connect(self.previous_image_requested.emit)
        self.previous_button.setEnabled(False)
        buttons.addWidget(self.previous_button)
        self.next_button = QPushButton("Next →")
        self.next_button.clicked.connect(self.next_image_requested.emit)
        self.next_button.setEnabled(False)
        buttons.addWidget(self.next_button)
        buttons.addSpacing(12)
        self.open_debug_button = QPushButton("Open image debug")
        self.open_debug_button.clicked.connect(self._emit_open_debug)
        buttons.addWidget(self.open_debug_button)
        buttons.addStretch(1)
        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_box.rejected.connect(self.reject)
        buttons.addWidget(close_box)
        root.addLayout(buttons)

    def _build_preview_panel(self) -> QFrame:
        card = make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        label = QLabel("Preview")
        label.setObjectName("cardTitle")
        layout.addWidget(label)
        self.preview = ImagePreview()
        layout.addWidget(self.preview, 1)
        self.path_label = QLabel("—")
        self.path_label.setObjectName("mutedLabel")
        self.path_label.setWordWrap(True)
        layout.addWidget(self.path_label)
        return card

    def _build_detail_tabs(self) -> QWidget:
        tabs = QTabWidget()
        tabs.addTab(self._build_metadata_tab(), "Metadata")
        tabs.addTab(self._build_laps_tab(), "Laps")
        tabs.addTab(self._build_text_tab("review_text"), "Review cases")
        tabs.addTab(self._build_extractions_tab(), "Extractions")
        tabs.addTab(self._build_attempts_tab(), "Attempts")
        return tabs

    def _build_metadata_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        self.metadata_grid = QGridLayout()
        self.metadata_grid.setHorizontalSpacing(10)
        self.metadata_grid.setVerticalSpacing(8)
        self.metadata_labels: dict[str, QLabel] = {}
        for row, field in enumerate(
            (
                "ID",
                "Current",
                "Semantic",
                "Hash",
                "Dimensions",
                "Format",
                "File size",
                "Date taken",
                "Date source",
                "Current path",
            )
        ):
            key = QLabel(field)
            key.setObjectName("mutedLabel")
            value = QLabel("—")
            value.setWordWrap(True)
            self.metadata_labels[field] = value
            self.metadata_grid.addWidget(key, row, 0)
            self.metadata_grid.addWidget(value, row, 1)
        layout.addLayout(self.metadata_grid)
        layout.addStretch(1)
        return page

    def _build_laps_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        self.laps_table = QTableWidget(0, 7)
        self.laps_table.setHorizontalHeaderLabels(["#", "Track", "Class", "Driver", "Car", "Best Lap", "Flags"])
        self.laps_table.verticalHeader().setVisible(False)
        self.laps_table.horizontalHeader().setStretchLastSection(True)
        self.laps_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.laps_table, 1)
        return page

    def _build_text_tab(self, attr_name: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        text = QTextEdit()
        text.setReadOnly(True)
        setattr(self, attr_name, text)
        layout.addWidget(text, 1)
        return page

    def _build_extractions_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        self.extractions_table = QTableWidget(0, 8)
        self.extractions_table.setHorizontalHeaderLabels([
            "Created", "Status", "Run", "Backend", "Model", "Prompt", "Raw", "Parsed"
        ])
        self.extractions_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.extractions_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.extractions_table.verticalHeader().setVisible(False)
        self.extractions_table.horizontalHeader().setStretchLastSection(True)
        self.extractions_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.extractions_table.clicked.connect(self._on_extraction_selected)
        layout.addWidget(self.extractions_table, 1)
        return page

    def _build_attempts_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        self.attempts_table = QTableWidget(0, 12)
        self.attempts_table.setHorizontalHeaderLabels([
            "#", "Reason", "Status", "Accepted", "Rejected", "Model", "Instance",
            "Context", "Thinking", "Duration", "TPS", "Issues",
        ])
        self.attempts_table.verticalHeader().setVisible(False)
        self.attempts_table.horizontalHeader().setStretchLastSection(True)
        self.attempts_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.attempts_table, 1)
        return page

    def set_navigation_state(self, *, has_previous: bool, has_next: bool) -> None:
        self.previous_button.setEnabled(has_previous)
        self.next_button.setEnabled(has_next)

    def show_detail(self, detail) -> None:
        image = detail.image
        self.title.setText(image.current_name or "Image")
        self.preview.set_image_path(detail.preview_path)
        self.path_label.setText(str(detail.preview_path or "No preview file available."))
        self.file_status.set_status(f"file: {image.file_status}", kind=_status_kind(image.file_status))
        self.best_status.set_status(f"best: {image.best_lap_status}", kind=_status_kind(image.best_lap_status))
        self._set_metadata(image)
        self._set_laps(detail.laps)
        self.review_text.setPlainText(_format_review_cases(detail.review_cases))
        self._set_extractions(detail.extraction_results)
        self._set_attempts(detail.extraction_attempts)

    def show_error(self, message: str) -> None:
        self.title.setText("Image Details")
        self.preview.set_image_path(None)
        self.path_label.setText(message)
        for label in self.metadata_labels.values():
            label.setText("—")
        self._set_laps([])
        self.review_text.setPlainText("—")
        self._set_extractions([])
        self._set_attempts([])
        self.open_debug_button.setEnabled(False)
        self.set_navigation_state(has_previous=False, has_next=False)

    def _set_metadata(self, image: ImageFile) -> None:
        values = {
            "ID": image.id,
            "Current": image.current_name or "—",
            "Semantic": image.semantic_name or "—",
            "Hash": image.file_hash,
            "Dimensions": f"{image.width_px or '—'} x {image.height_px or '—'}",
            "Format": f"{image.image_format or '—'} · {image.mime_type or '—'} · {image.color_mode or '—'}",
            "File size": _format_bytes(image.file_size_bytes),
            "Date taken": str(image.race_datetime or image.file_modified_at or "—"),
            "Date source": image.race_datetime_source or "—",
            "Current path": str(image.current_path or "—"),
        }
        for field, value in values.items():
            self.metadata_labels[field].setText(value)

    def _set_laps(self, laps) -> None:
        self.laps_table.setRowCount(0)
        for lap in laps:
            row = self.laps_table.rowCount()
            self.laps_table.insertRow(row)
            flags = []
            if lap.dirty:
                flags.append("dirty")
            if lap.is_best_lap:
                flags.append("best")
            values = [
                lap.lap_index,
                lap.track,
                lap.race_class,
                lap.driver,
                lap.car,
                lap.best_lap,
                " / ".join(flags) or "—",
            ]
            for column, value in enumerate(values):
                self.laps_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.laps_table.resizeColumnsToContents()

    def _set_extractions(self, results) -> None:
        ordered = sorted(list(results), key=_extraction_sort_key, reverse=True)
        self._extraction_result_ids = []
        self._selected_extraction_result_id = None
        self.extractions_table.setRowCount(0)
        for result in ordered:
            row = self.extractions_table.rowCount()
            self.extractions_table.insertRow(row)
            values = [
                getattr(result, "created_at", None) or "—",
                result.status,
                result.run_id,
                result.backend or "—",
                result.model or "—",
                result.prompt_name or "—",
                "raw" if result.has_raw_response else "no raw",
                "parsed" if result.has_parsed_result else "no parsed",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, result.id)
                self.extractions_table.setItem(row, column, item)
            self._extraction_result_ids.append(result.id)
        self.extractions_table.resizeColumnsToContents()
        if self._extraction_result_ids:
            self.extractions_table.selectRow(0)
            self._selected_extraction_result_id = self._extraction_result_ids[0]
        self.open_debug_button.setEnabled(self._selected_extraction_result_id is not None)

    def _set_attempts(self, attempts) -> None:
        self.attempts_table.setRowCount(0)
        for attempt in attempts:
            row = self.attempts_table.rowCount()
            self.attempts_table.insertRow(row)
            issues = ", ".join(attempt.validation_issues_json or [])
            values = [
                attempt.attempt_number,
                attempt.attempt_reason,
                attempt.status,
                "yes" if attempt.accepted else "no",
                attempt.rejected_reason or "—",
                attempt.model or "—",
                attempt.model_instance_id or "—",
                attempt.context_length or "—",
                attempt.reasoning_mode or "—",
                f"{attempt.duration_ms} ms" if attempt.duration_ms is not None else "—",
                f"{attempt.tokens_per_second:.1f}" if attempt.tokens_per_second is not None else "—",
                issues or attempt.parse_error or "—",
            ]
            for column, value in enumerate(values):
                self.attempts_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.attempts_table.resizeColumnsToContents()

    def _on_extraction_selected(self, index) -> None:
        item = self.extractions_table.item(index.row(), 0)
        self._selected_extraction_result_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.open_debug_button.setEnabled(self._selected_extraction_result_id is not None)

    def _emit_open_debug(self) -> None:
        if self._selected_extraction_result_id is None:
            return
        self.open_debug_requested.emit(self._selected_extraction_result_id)


def _format_laps(laps) -> str:
    if not laps:
        return "No laps extracted for this image."
    lines = []
    for lap in laps:
        flags = []
        if lap.dirty:
            flags.append("dirty")
        if lap.is_best_lap:
            flags.append("best")
        suffix = f" [{' / '.join(flags)}]" if flags else ""
        lines.append(
            f"#{lap.lap_index} · {lap.track} · {lap.race_class} · {lap.driver} · {lap.car} · {lap.best_lap}{suffix}"
        )
    return "\n".join(lines)


def _format_review_cases(cases) -> str:
    if not cases:
        return "No linked review cases."
    lines = []
    for case in cases:
        number = case.case_number or case.id
        suggestions = f" · suggestions={case.track_suggestions}" if case.track_suggestions else ""
        lines.append(
            f"#{number} · {case.status} · {case.reason} · "
            f"{case.current_track or case.track} · "
            f"{case.current_race_class or case.race_class} · "
            f"{_current_lap_label(case)}{suggestions}"
        )
    return "\n".join(lines)


def _current_lap_label(case) -> str:
    lap = case.current_best_lap if case.current_best_lap is not None else case.best_lap
    if not lap:
        return "—"
    if case.current_dirty:
        return f"{lap} dirty"
    return lap


def _format_extractions(results) -> str:
    if not results:
        return "No linked extraction results."
    lines = []
    for result in results:
        raw = "raw" if result.has_raw_response else "no raw"
        parsed = "parsed" if result.has_parsed_result else "no parsed"
        error = f" · error={result.error_message}" if result.error_message else ""
        lines.append(
            f"{result.id} · run={result.run_id} · {result.status} · {result.backend or '—'} · {result.model or '—'} · {result.prompt_name or '—'} · {raw} · {parsed}{error}"
        )
    return "\n".join(lines)


def _extraction_sort_key(result):
    return str(getattr(result, "created_at", None) or "")


def _status_kind(status: str) -> str:
    if status in {"available", "contributing", "ok", "open"}:
        return "success"
    if status in {"missing", "error"}:
        return "danger"
    if status in {"pending", "non_contributing"}:
        return "warning"
    return "neutral"


def _format_bytes(value: int | None) -> str:
    if value is None:
        return "—"
    if value < 1024:
        return f"{value} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value / (1024 * 1024):.2f} MB"

