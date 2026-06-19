from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QSplitter,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...application.gui_read_service import GuiLap, GuiReviewCase
from ..models.review_table_model import ReviewTableModel
from ..widgets.card import make_card
from ..widgets.filter_controls import fit_combo_to_contents, resize_combo_to_contents
from ..widgets.image_preview import ImagePreview


class ReviewQueueView(QWidget):
    refresh_requested = Signal(str, object, object, object)
    filters_changed = Signal(str, object, object, object)
    case_selected = Signal(str)
    confirm_dirty_requested = Signal()
    mark_clean_requested = Signal()
    set_track_requested = Signal(str)
    set_weather_requested = Signal(str)
    set_race_class_requested = Signal(str)
    set_car_requested = Signal(str)
    set_driver_name_requested = Signal(str)
    ignore_requested = Signal()
    reopen_requested = Signal()
    open_image_detail_requested = Signal(str)
    next_requested = Signal()
    previous_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model = ReviewTableModel()
        self._current_case: GuiReviewCase | None = None
        self._track_options: list[str] = []
        self._primary_buttons: list[QPushButton] = []
        self._primary_callbacks: list[Callable[[], None]] = []
        self._primary_index = 0
        self._build_ui()
        self._install_shortcuts()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        root.addWidget(self._build_filter_bar())

        main = QSplitter(Qt.Orientation.Horizontal)
        left = QSplitter(Qt.Orientation.Vertical)
        left.addWidget(self._build_preview_panel())
        left.addWidget(self._build_queue_panel())
        left.setSizes([520, 300])
        main.addWidget(left)
        main.addWidget(self._build_detail_panel())
        main.setSizes([760, 520])
        root.addWidget(main, 1)

    def _build_filter_bar(self) -> QFrame:
        card = make_card()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        self.status_filter = QComboBox()
        self.status_filter.addItems(["open", "resolved", "ignored", "all"])
        self.reason_filter = QComboBox()
        self.reason_filter.addItem("all")
        self.outcome_filter = QComboBox()
        self.outcome_filter.addItems(["all", "pending", "confirmed", "model_error", "ignored"])
        self.run_filter = QComboBox()
        self.run_filter.addItem("all")
        for combo in (self.status_filter, self.reason_filter, self.outcome_filter, self.run_filter):
            fit_combo_to_contents(combo)

        for label, combo in (
            ("Status", self.status_filter),
            ("Reason", self.reason_filter),
            ("Outcome", self.outcome_filter),
            ("Run", self.run_filter),
        ):
            layout.addWidget(QLabel(label))
            layout.addWidget(combo)

        for combo in (self.status_filter, self.reason_filter, self.outcome_filter, self.run_filter):
            combo.currentTextChanged.connect(lambda _text: self._emit_filters_changed())

        layout.addStretch(1)
        return card

    def _build_queue_panel(self) -> QFrame:
        card = make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        header = QHBoxLayout()
        title = QLabel("Case Queue")
        title.setObjectName("cardTitle")
        self.previous_button = QPushButton("Previous")
        self.next_button = QPushButton("Next")
        self.previous_button.clicked.connect(self.previous_requested)
        self.next_button.clicked.connect(self.next_requested)
        header.addWidget(title, 1)
        header.addWidget(self.previous_button)
        header.addWidget(self.next_button)
        layout.addLayout(header)

        self.table = QTableView()
        self.table.setModel(self._model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.clicked.connect(self._on_table_clicked)
        layout.addWidget(self.table, 1)
        return card

    def _build_preview_panel(self) -> QFrame:
        card = make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        title = QLabel("Image")
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        self.preview = ImagePreview()
        layout.addWidget(self.preview, 1)
        return card

    def _build_detail_panel(self) -> QFrame:
        card = make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        title = QLabel("Details and Actions")
        title.setObjectName("cardTitle")
        layout.addWidget(title)

        self.detail_grid = QGridLayout()
        self.detail_grid.setHorizontalSpacing(10)
        self.detail_grid.setVerticalSpacing(8)
        self.detail_labels: dict[str, QLabel] = {}
        for row, field in enumerate(("Case", "Stable ID", "Outcome", "Reason", "Trigger", "Model value", "Corrected value", "Decision", "Error", "Resolution", "File", "Current track", "Current class", "Current weather", "Temp", "Current driver", "Current car", "Current lap")):
            key = QLabel(field)
            key.setObjectName("mutedLabel")
            value = QLabel("—")
            value.setWordWrap(True)
            self.detail_labels[field] = value
            self.detail_grid.addWidget(key, row, 0)
            self.detail_grid.addWidget(value, row, 1)
        layout.addLayout(self.detail_grid)

        self.reason_note = QLabel("")
        self.reason_note.setObjectName("mutedLabel")
        self.reason_note.setWordWrap(True)
        layout.addWidget(self.reason_note)

        suggestions_label = QLabel("Suggestions")
        suggestions_label.setObjectName("mutedLabel")
        layout.addWidget(suggestions_label)
        self.suggestions = QTextEdit()
        self.suggestions.setReadOnly(True)
        self.suggestions.setMaximumHeight(120)
        layout.addWidget(self.suggestions)

        laps_label = QLabel("Laps extracted from image")
        laps_label.setObjectName("mutedLabel")
        layout.addWidget(laps_label)
        self.laps = QTableWidget(0, 6)
        self.laps.setHorizontalHeaderLabels(["#", "Driver", "Car", "Class", "Best lap", "Flags"])
        self.laps.verticalHeader().setVisible(False)
        self.laps.verticalHeader().setDefaultSectionSize(24)
        self.laps.horizontalHeader().setStretchLastSection(True)
        self.laps.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.laps.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        self.laps.setMinimumHeight(_lap_table_height(self.laps, rows=13))
        layout.addWidget(self.laps)

        self.action_stack = QStackedWidget()
        self.action_stack.addWidget(self._build_dirty_actions())
        self.action_stack.addWidget(self._build_track_actions())
        self.action_stack.addWidget(self._build_weather_actions())
        self.action_stack.addWidget(self._build_class_actions())
        self.action_stack.addWidget(self._build_car_actions())
        self.action_stack.addWidget(self._build_driver_name_actions())
        self.action_stack.addWidget(self._build_generic_actions())
        layout.addWidget(self.action_stack)
        self.primary_hint = QLabel("")
        self.primary_hint.setObjectName("mutedLabel")
        self.primary_hint.setWordWrap(True)
        layout.addWidget(self.primary_hint)

        footer = QHBoxLayout()
        self.ignore_button = QPushButton("Ignore case")
        self.reopen_button = QPushButton("Reopen case")
        self.ignore_button.clicked.connect(self.ignore_requested)
        self.reopen_button.clicked.connect(self.reopen_requested)
        footer.addWidget(self.ignore_button)
        footer.addWidget(self.reopen_button)
        footer.addStretch(1)
        self.open_detail_button = QPushButton("Image details")
        self.open_detail_button.clicked.connect(self._emit_open_image_detail)
        footer.addWidget(self.open_detail_button)
        layout.addLayout(footer)
        self._set_actions_enabled(False)
        return card

    def _build_dirty_actions(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.confirm_dirty_button = QPushButton("Dirty")
        self.mark_clean_button = QPushButton("Clean")
        self.confirm_dirty_button.clicked.connect(self.confirm_dirty_requested)
        self.mark_clean_button.clicked.connect(self.mark_clean_requested)
        layout.addWidget(self.confirm_dirty_button)
        layout.addWidget(self.mark_clean_button)
        layout.addStretch(1)
        return page

    def _build_track_actions(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.track_combo = QComboBox()
        self.apply_track_button = QPushButton("Apply track")
        self.apply_track_button.clicked.connect(lambda: self.set_track_requested.emit(self.track_combo.currentText()))
        layout.addWidget(self.track_combo, 1)
        layout.addWidget(self.apply_track_button)
        return page

    def _build_weather_actions(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.rain_button = QPushButton("Rain")
        self.dry_button = QPushButton("Dry")
        self.rain_button.clicked.connect(lambda: self.set_weather_requested.emit("rain"))
        self.dry_button.clicked.connect(lambda: self.set_weather_requested.emit("dry"))
        layout.addWidget(self.rain_button)
        layout.addWidget(self.dry_button)
        layout.addStretch(1)
        return page

    def _build_class_actions(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.class_combo = QComboBox()
        self.class_combo.addItems(["E", "D", "C", "B", "A", "TCR", "S", "R", "P", "X", "Mixed", "Unknown"])
        self.apply_class_button = QPushButton("Apply class")
        self.apply_class_button.clicked.connect(lambda: self.set_race_class_requested.emit(self.class_combo.currentText()))
        layout.addWidget(self.class_combo)
        layout.addWidget(self.apply_class_button)
        layout.addStretch(1)
        return page

    def _build_car_actions(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.car_edit = QLineEdit()
        self.car_edit.setPlaceholderText("Correct car")
        self.apply_car_button = QPushButton("Apply car")
        self.apply_car_button.clicked.connect(lambda: self.set_car_requested.emit(self.car_edit.text()))
        layout.addWidget(self.car_edit, 1)
        layout.addWidget(self.apply_car_button)
        return page

    def _build_driver_name_actions(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.driver_name_edit = QLineEdit()
        self.driver_name_edit.setPlaceholderText("Correct driver name")
        self.apply_driver_name_button = QPushButton("Apply driver name")
        self.apply_driver_name_button.clicked.connect(lambda: self.set_driver_name_requested.emit(self.driver_name_edit.text()))
        layout.addWidget(self.driver_name_edit, 1)
        layout.addWidget(self.apply_driver_name_button)
        return page

    def _build_generic_actions(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel("No semantic action is available for this reason. Inspect the image or ignore the case.")
        label.setObjectName("mutedLabel")
        label.setWordWrap(True)
        layout.addWidget(label, 1)
        return page

    def set_cases(self, cases: list[GuiReviewCase]) -> None:
        self._model.set_cases(cases)
        self.table.resizeColumnsToContents()
        if cases:
            self.table.selectRow(0)
        else:
            self.show_selection(None, None, [], None)

    def set_filter_options(self, options) -> None:
        self._sync_combo(self.reason_filter, _option_values(options, "reasons"))
        self._sync_combo(self.outcome_filter, _option_values(options, "outcomes"), preserve_static=True)

    def set_track_options(self, tracks: list[str]) -> None:
        self._track_options = list(tracks)
        current = self.track_combo.currentText() if hasattr(self, "track_combo") else ""
        self.track_combo.blockSignals(True)
        self.track_combo.clear()
        self.track_combo.addItems(self._track_options)
        if current in self._track_options:
            self.track_combo.setCurrentText(current)
        self.track_combo.blockSignals(False)

    def set_run_options(self, runs: list[object]) -> None:
        self._sync_combo(self.run_filter, runs)

    def show_selection(self, case: GuiReviewCase | None, image, laps: list[GuiLap], preview_path: Path | None) -> None:
        self._current_case = case
        self.preview.set_image_path(preview_path)
        self._set_actions_enabled(case is not None)
        if case is None:
            for label in self.detail_labels.values():
                label.setText("—")
            self.suggestions.clear()
            self.laps.setRowCount(0)
            self.reason_note.setText("No case selected.")
            self.action_stack.setCurrentIndex(6)
            self._set_primary_actions([], [])
            return
        self._select_case_row(case.id)
        values = {
            "Case": str(case.case_number or case.id),
            "Stable ID": case.business_key,
            "Outcome": case.outcome,
            "Reason": case.reason,
            "Trigger": case.trigger or "—",
            "Model value": case.model_value or "—",
            "Corrected value": case.corrected_value or "—",
            "Decision": _decision_label(case),
            "Error": case.error_type or "—",
            "Resolution": case.resolution_note or "—",
            "File": case.source_file,
            "Current track": case.current_track or case.track,
            "Current class": case.current_race_class or case.race_class,
            "Current weather": case.current_weather or case.weather,
            "Temp": "—" if case.temp_f is None else f"{case.temp_f:g} °F",
            "Current driver": case.current_driver or case.driver or "—",
            "Current car": case.current_car or case.car or "—",
            "Current lap": _current_lap_label(case),
        }
        for field, value in values.items():
            self.detail_labels[field].setText(value)
        suggestions = []
        if case.track_suggestions:
            suggestions.append("Track suggestions: " + ", ".join(case.track_suggestions))
        self.suggestions.setPlainText("\n".join(suggestions) if suggestions else "—")
        self._set_laps(laps)
        self._show_reason_actions(case)

    def show_message(self, message: str) -> None:
        self.suggestions.setPlainText(message)

    def refresh_current_filters(self) -> None:
        self._emit_refresh()

    def _emit_refresh(self) -> None:
        self.refresh_requested.emit(*self._filter_values())

    def _emit_filters_changed(self) -> None:
        self.filters_changed.emit(*self._filter_values())

    def _filter_values(self) -> tuple[str, object, object, object]:
        status = self.status_filter.currentText()
        reason = self.reason_filter.currentText()
        outcome = self.outcome_filter.currentText()
        run_id = _combo_value(self.run_filter)
        return (
            status,
            None if reason == "all" else reason,
            None if run_id == "all" else run_id,
            None if outcome == "all" else outcome,
        )

    def _on_table_clicked(self, index) -> None:
        case = self._model.case_at(index.row())
        if case is not None:
            self.case_selected.emit(case.id)

    def _emit_open_image_detail(self) -> None:
        if self._current_case and self._current_case.image_file_id:
            self.open_image_detail_requested.emit(self._current_case.image_file_id)

    def _set_actions_enabled(self, enabled: bool) -> None:
        for button in (
            self.confirm_dirty_button,
            self.mark_clean_button,
            self.apply_track_button,
            self.rain_button,
            self.dry_button,
            self.apply_class_button,
            self.apply_car_button,
            self.apply_driver_name_button,
            self.ignore_button,
            self.reopen_button,
            self.open_detail_button,
            self.previous_button,
            self.next_button,
        ):
            button.setEnabled(enabled)

    def _sync_combo(self, combo: QComboBox, values, *, preserve_static: bool = False) -> bool:
        current = _combo_value(combo) or "all"
        existing = []
        if preserve_static:
            for index in range(combo.count()):
                existing.append((str(combo.itemData(index) or combo.itemText(index)), combo.itemText(index)))
        options = [_normalise_option(value) for value in values if value]
        unique = [("all", "all")] + sorted(set(existing + options), key=lambda item: item[1].lower())
        option_ids = {option_id for option_id, _label in unique}
        next_value = current if current in option_ids else "all"
        combo.blockSignals(True)
        combo.clear()
        for option_id, label in unique:
            combo.addItem(label, option_id)
        index = combo.findData(next_value)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)
        resize_combo_to_contents(combo)
        return next_value != current

    def _show_reason_actions(self, case: GuiReviewCase) -> None:
        reason = str(case.reason)
        if reason == "dirty_lap":
            self.reason_note.setText(
                "The model detected a dirty lap. Confirm the detection or mark the lap clean."
            )
            self.action_stack.setCurrentIndex(0)
            self._set_primary_actions(
                [self.confirm_dirty_button, self.mark_clean_button],
                [self.confirm_dirty_requested.emit, self.mark_clean_requested.emit],
            )
        elif reason == "track":
            self.reason_note.setText("Track was not identified with enough confidence.")
            if case.track and case.track in self._track_options:
                self.track_combo.setCurrentText(case.track)
            self.action_stack.setCurrentIndex(1)
            self._set_primary_actions(
                [self.apply_track_button],
                [lambda: self.set_track_requested.emit(self.track_combo.currentText())],
            )
        elif reason == "weather":
            self.reason_note.setText("Weather condition was not identified with enough confidence.")
            self.action_stack.setCurrentIndex(2)
            preferred_index = 1 if str(case.weather).lower() == "dry" else 0
            self._set_primary_actions(
                [self.rain_button, self.dry_button],
                [lambda: self.set_weather_requested.emit("rain"), lambda: self.set_weather_requested.emit("dry")],
                selected=preferred_index,
            )
        elif reason == "race_class":
            self.reason_note.setText("Race class may be incorrect. Apply the corrected class.")
            if case.race_class:
                self.class_combo.setCurrentText(case.race_class)
            self.action_stack.setCurrentIndex(3)
            self._set_primary_actions(
                [self.apply_class_button],
                [lambda: self.set_race_class_requested.emit(self.class_combo.currentText())],
            )
        elif reason == "car":
            self.reason_note.setText("Car name may be incorrect. Apply the corrected car.")
            self.car_edit.setText(case.car or "")
            self.action_stack.setCurrentIndex(4)
            self._set_primary_actions(
                [self.apply_car_button],
                [lambda: self.set_car_requested.emit(self.car_edit.text())],
            )
        elif reason == "driver_name":
            self.reason_note.setText("Driver name may be incorrect. Apply the corrected driver name.")
            self.driver_name_edit.setText(case.driver or "")
            self.action_stack.setCurrentIndex(5)
            self._set_primary_actions(
                [self.apply_driver_name_button],
                [lambda: self.set_driver_name_requested.emit(self.driver_name_edit.text())],
            )
        else:
            self.reason_note.setText(f"Review reason: {case.reason}")
            self.action_stack.setCurrentIndex(6)
            self._set_primary_actions([], [])

    def _install_shortcuts(self) -> None:
        shortcuts = (
            ("Up", self.previous_requested.emit),
            ("Down", self.next_requested.emit),
            ("Left", lambda: self._select_primary_delta(-1)),
            ("Right", lambda: self._select_primary_delta(1)),
            ("Return", self._activate_primary_action),
            ("Enter", self._activate_primary_action),
            ("D", self.confirm_dirty_requested.emit),
            ("C", self.mark_clean_requested.emit),
            ("I", self.ignore_requested.emit),
        )
        for key, callback in shortcuts:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)

    def _set_primary_actions(
        self,
        buttons: list[QPushButton],
        callbacks: list[Callable[[], None]],
        *,
        selected: int = 0,
    ) -> None:
        for button in self._primary_buttons:
            button.setStyleSheet("")
        self._primary_buttons = list(buttons)
        self._primary_callbacks = list(callbacks)
        self._set_primary_index(selected)

    def _set_primary_index(self, index: int) -> None:
        if not self._primary_buttons:
            self._primary_index = 0
            self.primary_hint.setText("No primary keyboard action for this case.")
            return
        self._primary_index = max(0, min(len(self._primary_buttons) - 1, index))
        for button_index, button in enumerate(self._primary_buttons):
            button.setStyleSheet(
                "border: 2px solid #0F6CBD; font-weight: 700;"
                if button_index == self._primary_index
                else ""
            )
        label = self._primary_buttons[self._primary_index].text()
        self.primary_hint.setText(f"Enter applies: {label}. Use ←/→ to change the selected action.")

    def _select_primary_delta(self, delta: int) -> None:
        if not self._primary_buttons:
            return
        next_index = (self._primary_index + delta) % len(self._primary_buttons)
        self._set_primary_index(next_index)

    def _activate_primary_action(self) -> None:
        if not self._primary_callbacks:
            return
        self._primary_callbacks[self._primary_index]()

    def _select_case_row(self, case_id: str) -> None:
        for row in range(self._model.rowCount()):
            case = self._model.case_at(row)
            if case is not None and case.id == case_id:
                self.table.selectRow(row)
                self.table.scrollTo(self._model.index(row, 0))
                return

    def _set_laps(self, laps: list[GuiLap]) -> None:
        self.laps.setRowCount(0)
        for lap in sorted(laps, key=lambda item: item.lap_index):
            row = self.laps.rowCount()
            self.laps.insertRow(row)
            flags = []
            if lap.dirty:
                flags.append("dirty")
            if lap.is_best_lap:
                flags.append("best")
            values = [
                lap.lap_index + 1,
                lap.driver,
                lap.car,
                lap.car_class,
                lap.best_lap,
                ", ".join(flags) or "-",
            ]
            for column, value in enumerate(values):
                self.laps.setItem(row, column, QTableWidgetItem(str(value)))
        self.laps.resizeColumnsToContents()


def _combo_value(combo: QComboBox) -> str:
    data = combo.currentData()
    return str(data) if data is not None else combo.currentText()


def _normalise_option(value) -> tuple[str, str]:
    option_id = getattr(value, "id", value)
    label = getattr(value, "label", value)
    return str(option_id), str(label)


def _option_values(options, key: str):
    if isinstance(options, dict):
        return options.get(key, [])
    return getattr(options, key, [])


def _lap_table_height(table: QTableWidget, *, rows: int) -> int:
    header_height = table.horizontalHeader().sizeHint().height()
    row_height = table.verticalHeader().defaultSectionSize()
    return header_height + (row_height * rows) + (2 * table.frameWidth()) + 8


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
