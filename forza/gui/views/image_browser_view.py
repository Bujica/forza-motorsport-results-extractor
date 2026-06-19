from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...schemas import ImageFile
from ..models.image_table_model import ImageTableModel
from ..widgets.batch_action_bar import BatchActionBar
from ..widgets.card import make_card
from ..widgets.confirmation_dialogs import confirm_batch, info, warning
from ..widgets.filter_controls import fit_combo_to_contents, resize_combo_to_contents
from ..widgets.image_preview import ImagePreview


class ImageBrowserView(QWidget):
    refresh_requested = Signal(str, str, str, str, str, str)
    scan_requested = Signal()
    process_selected_requested = Signal(object)
    selection_changed = Signal(object)
    rename_requested = Signal(object)
    export_requested = Signal(object, object)
    delete_requested = Signal(object)
    rescan_selected_requested = Signal(object)
    open_detail_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model = ImageTableModel()
        self._images: list[ImageFile] = []
        self._selected_ids: list[str] = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        root.addWidget(self._build_filter_bar())
        self.action_bar = BatchActionBar()
        self.action_bar.process_requested.connect(self._emit_process_selected)
        self.action_bar.rename_requested.connect(self._confirm_rename)
        self.action_bar.export_requested.connect(self._choose_export_destination)
        self.action_bar.rescan_requested.connect(self._emit_rescan_selected)
        self.action_bar.delete_requested.connect(self._confirm_delete)
        root.addWidget(self.action_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_table_panel())
        splitter.addWidget(self._build_side_panel())
        splitter.setSizes([820, 360])
        root.addWidget(splitter, 1)

    def _build_filter_bar(self) -> QFrame:
        card = make_card()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        self.best_filter = fit_combo_to_contents(QComboBox())
        self.best_filter.addItems(["all", "pending", "contributing", "non_contributing"])
        self.file_filter = fit_combo_to_contents(QComboBox())
        self.file_filter.addItems(["all", "available", "missing"])
        self.process_filter = fit_combo_to_contents(QComboBox())
        self.process_filter.addItems(["all", "unprocessed", "processing", "processed_ok", "processed_error", "cancelled", "skipped"])
        self.inventory_filter = fit_combo_to_contents(QComboBox())
        self.inventory_filter.addItem("all", "all")
        self.inventory_filter.addItem("duplicate groups", "duplicate")
        self.track_filter = fit_combo_to_contents(QComboBox())
        self.track_filter.addItem("all")
        self.run_filter = fit_combo_to_contents(QComboBox())
        self.run_filter.addItem("all")

        for combo in (
            self.best_filter,
            self.file_filter,
            self.process_filter,
            self.inventory_filter,
            self.track_filter,
            self.run_filter,
        ):
            resize_combo_to_contents(combo)

        for label, combo in (
            ("Best", self.best_filter),
            ("File", self.file_filter),
            ("Process", self.process_filter),
            ("Track", self.track_filter),
            ("Inventory", self.inventory_filter),
            ("Run", self.run_filter),
        ):
            layout.addWidget(QLabel(label))
            layout.addWidget(combo)

        for combo in (
            self.best_filter,
            self.file_filter,
            self.process_filter,
            self.inventory_filter,
            self.track_filter,
            self.run_filter,
        ):
            combo.currentTextChanged.connect(lambda _text: self._emit_refresh())

        layout.addStretch(1)
        self.scan_status = QLabel("")
        self.scan_status.setObjectName("mutedLabel")
        layout.addWidget(self.scan_status)
        self.scan_button = QPushButton("Scan folder")
        self.scan_button.clicked.connect(self.scan_requested)
        layout.addWidget(self.scan_button)
        return card

    def _build_table_panel(self) -> QFrame:
        card = make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        title = QLabel("Image inventory")
        title.setObjectName("cardTitle")
        layout.addWidget(title)

        self.table = QTableView()
        self.table.setModel(self._model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table, 1)
        return card

    def _build_side_panel(self) -> QFrame:
        card = make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        title = QLabel("Preview / selection")
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        self.preview = ImagePreview()
        self.preview.setMinimumHeight(260)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.preview)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        splitter.addWidget(self.detail)
        splitter.setSizes([300, 220])
        layout.addWidget(splitter, 1)

        self.open_detail_button = QPushButton("Image details")
        self.open_detail_button.clicked.connect(self._emit_open_detail)
        self.open_detail_button.setEnabled(False)
        layout.addWidget(self.open_detail_button)
        return card

    def set_images(self, images: list[ImageFile]) -> None:
        self._images = list(images)
        self._model.set_images(self._images)
        self.table.resizeColumnsToContents()
        self._selected_ids = []
        self.action_bar.set_selection([])
        self._render_selection([], None)

    def visible_image_ids(self) -> list[str]:
        ids: list[str] = []
        for row in range(self._model.rowCount()):
            image = self._model.image_at(row)
            if image is not None:
                ids.append(image.id)
        return ids

    def set_filter_options(self, options) -> None:
        changed = False
        changed |= self._sync_combo(self.track_filter, getattr(options, "tracks", []))
        changed |= self._sync_combo(self.run_filter, getattr(options, "runs", []))
        if changed:
            self._emit_refresh()

    def show_selection(
        self,
        selected: list[ImageFile],
        current: ImageFile | None,
    ) -> None:
        self.action_bar.set_selection(selected)
        self._render_selection(selected, current)

    def show_message(self, message: str) -> None:
        info(self, title="Images", message=message)

    def show_warning(self, message: str) -> None:
        warning(self, title="Images", message=message)

    def set_syncing(self, running: bool) -> None:
        self.scan_button.setEnabled(not running)
        self.scan_status.setText("Syncing input folder..." if running else "")

    def confirm_rename_plan(self, plan) -> bool:
        plans = list(getattr(plan, "plans", []))
        summary = [
            f"Selected total: {getattr(plan, 'total', 0)}",
            f"Would rename: {getattr(plan, 'would_change', 0)}",
            f"Missing plan: {getattr(plan, 'missing', 0)}",
        ]
        lines = [
            f"{item.source_path.name} -> {item.target_path.name}"
            for item in plans
            if item.would_change
        ]
        if not lines:
            lines = ["No filename changes are required."]
        return confirm_batch(
            self,
            title="Confirm Metadata Rename",
            action="apply this rename plan",
            names=lines,
            summary=summary,
        )

    def _emit_refresh(self) -> None:
        self.refresh_requested.emit(
            self.file_filter.currentText(),
            self.best_filter.currentText(),
            self.inventory_filter.currentText(),
            _combo_value(self.track_filter),
            _combo_value(self.run_filter),
            self.process_filter.currentText(),
        )

    def _on_selection_changed(self) -> None:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        images = [self._model.image_at(row) for row in rows]
        selected = [image for image in images if image is not None]
        self._selected_ids = [image.id for image in selected]
        self.selection_changed.emit(self._selected_ids)

    def _render_selection(self, selected: list[ImageFile], current: ImageFile | None) -> None:
        self.open_detail_button.setEnabled(current is not None)
        if current is None:
            if selected:
                self.preview.set_image_path(None)
                self.detail.setPlainText(_selection_summary(selected))
            else:
                self.preview.set_image_path(None)
                self.detail.setPlainText("No image selected.")
            return
        self.preview.set_image_path(Path(current.current_path) if current.current_path else None)
        self.detail.setPlainText(_image_detail(current))

    def _confirm_rename(self) -> None:
        if self._selected_ids:
            self.rename_requested.emit(self._selected_ids)

    def _choose_export_destination(self) -> None:
        if not self._selected_ids:
            return
        directory = QFileDialog.getExistingDirectory(self, "Choose export destination")
        if not directory:
            return
        self.export_requested.emit(self._selected_ids, Path(directory))

    def _confirm_delete(self) -> None:
        names = self._selected_names()
        if not names:
            return
        if confirm_batch(
            self,
            title="Delete Images",
            action="permanently delete the selected files and their database records",
            names=names,
        ):
            self.delete_requested.emit(self._selected_ids)

    def _emit_open_detail(self) -> None:
        if len(self._selected_ids) == 1:
            self.open_detail_requested.emit(self._selected_ids[0])

    def _emit_process_selected(self) -> None:
        if self._selected_ids:
            self.process_selected_requested.emit(self._selected_ids)

    def _emit_rescan_selected(self) -> None:
        if self._selected_ids:
            self.rescan_selected_requested.emit(self._selected_ids)

    def _selected_names(self) -> list[str]:
        names = []
        selected = set(self._selected_ids)
        for image in self._images:
            if image.id in selected:
                names.append(image.current_name or "Image")
        return names

    def _sync_combo(self, combo: QComboBox, values) -> bool:
        current = _combo_value(combo) or "all"
        options = [_normalise_option(value) for value in values if value]
        unique = [("all", "all")] + sorted(set(options), key=lambda item: item[1].lower())
        option_ids = {option_id for option_id, _label in unique}
        next_value = current if current in option_ids else "all"
        combo.blockSignals(True)
        combo.clear()
        for option_id, label in unique:
            combo.addItem(label, option_id)
        index = combo.findData(next_value)
        combo.setCurrentIndex(index if index >= 0 else 0)
        resize_combo_to_contents(combo)
        combo.blockSignals(False)
        return next_value != current


def _image_detail(image: ImageFile) -> str:
    lines = [
        f"ID: {image.id}",
        f"Current: {image.current_name or '—'}",
        f"Semantic: {image.semantic_name or '—'}",
        f"file_hash: {image.file_hash}",
        f"file_status: {image.file_status}",
        f"duplicate: {'yes' if image.duplicate_of_image_file_id else 'no'}",
        f"duplicate_of_image_file_id: {image.duplicate_of_image_file_id or '—'}",
        f"processing_status: {image.processing_status}",
        f"best_lap_status: {image.best_lap_status}",
        f"current_path: {image.current_path or '—'}",
    ]
    return "\n".join(lines)


def _selection_summary(images: list[ImageFile]) -> str:
    total = len(images)
    missing = sum(1 for image in images if image.file_status == "missing")
    duplicates = sum(1 for image in images if image.duplicate_of_image_file_id)
    unprocessed = sum(1 for image in images if str(image.processing_status) == "unprocessed")
    errors = sum(1 for image in images if str(image.processing_status) == "processed_error")
    skipped = sum(1 for image in images if str(image.processing_status) == "skipped")
    return (
        f"Selected: {total}\n"
        f"Missing: {missing}\n"
        f"Duplicates: {duplicates}\n"
        f"Unprocessed: {unprocessed}\n"
        f"Skipped: {skipped}\n"
        f"Processing errors: {errors}"
    )


def _combo_value(combo: QComboBox) -> str:
    data = combo.currentData()
    return str(data) if data is not None else combo.currentText()


def _normalise_option(value) -> tuple[str, str]:
    option_id = getattr(value, "id", value)
    label = getattr(value, "label", value)
    return str(option_id), str(label)
