from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QSpinBox, QStyledItemDelegate
from PySide6.QtWidgets import (
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..models.settings_table_model import SettingsTableModel
from ..widgets.card import make_card
from ..widgets.confirmation_dialogs import confirm_batch, info, warning
from ..widgets.status_badge import StatusBadge


class SettingsView(QWidget):
    refresh_requested = Signal()
    preview_requested = Signal(object)
    save_requested = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._settings_model = SettingsTableModel()
        self._pending_changes: dict[str, str] = {}
        self._build_ui()
        self._settings_model.value_changed.connect(self._on_value_changed)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        header = QHBoxLayout()
        refresh = QPushButton("Discard / reload")
        refresh.clicked.connect(self._discard_changes)
        self.save_button = QPushButton("Save changes")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._confirm_save)
        header.addStretch(1)
        header.addWidget(refresh)
        header.addWidget(self.save_button)
        root.addLayout(header)

        root.addWidget(self._build_validation_bar())

        root.addWidget(self._build_settings_table(), 1)

    def _build_validation_bar(self) -> QFrame:
        card = make_card()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        self.validation_title = QLabel("Validation")
        self.validation_title.setObjectName("cardTitle")
        self.validation_badge = StatusBadge()
        self.validation_text = QLabel("—")
        self.validation_text.setObjectName("mutedLabel")
        self.validation_text.setWordWrap(True)
        layout.addWidget(self.validation_title)
        layout.addWidget(self.validation_badge)
        layout.addWidget(self.validation_text, 1)
        note = QLabel("Edit values in the Value column. Saving validates first, creates a backup of the current INI, then writes the file.")
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        layout.addWidget(note, 1)
        return card

    def show_settings(self, snapshot) -> None:
        self._settings_model.set_sections(
            [
                ("Paths", snapshot.paths),
                ("Backend / Model / Prompt", snapshot.llm),
                ("Runtime / Image / PDF / Validation", snapshot.runtime),
            ]
        )
        self._apply_group_spans()
        kind = "success" if snapshot.validation_ok else "danger"
        text = "valid" if snapshot.validation_ok else "invalid"
        if snapshot.dirty and snapshot.validation_ok:
            kind = "warning"
            text = "changed"
        self.validation_badge.set_status(text, kind=kind)
        self.validation_text.setText(snapshot.validation_message)
        if not snapshot.dirty:
            self._pending_changes = {}
        self.save_button.setEnabled(bool(self._pending_changes))

    def show_message(self, message: str) -> None:
        info(self, title="Settings", message=message)

    def show_warning(self, message: str) -> None:
        warning(self, title="Settings", message=message)

    def _on_value_changed(self, key: str, value: str) -> None:
        self._pending_changes[key] = value
        self.save_button.setEnabled(True)
        self.preview_requested.emit(dict(self._pending_changes))

    def _discard_changes(self) -> None:
        self._pending_changes = {}
        self.save_button.setEnabled(False)
        self.refresh_requested.emit()

    def _confirm_save(self) -> None:
        if not self._pending_changes:
            return
        names = [f"{key} = {value}" for key, value in sorted(self._pending_changes.items())]
        if confirm_batch(self, title="Save Configuration", action="validate, back up, and save INI changes", names=names):
            self.save_requested.emit(dict(self._pending_changes))

    def _build_settings_table(self) -> QFrame:
        card = make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        self.settings_table = QTableView()
        self.settings_table.setModel(self._settings_model)
        self.settings_table.setItemDelegateForColumn(1, SettingsValueDelegate(self.settings_table))
        self.settings_table.setAlternatingRowColors(True)
        self.settings_table.verticalHeader().setVisible(False)
        self.settings_table.horizontalHeader().setStretchLastSection(True)
        self.settings_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.settings_table.verticalHeader().setDefaultSectionSize(24)
        layout.addWidget(self.settings_table, 1)
        return card

    def _apply_group_spans(self) -> None:
        self.settings_table.clearSpans()
        for row in self._settings_model.group_rows():
            self.settings_table.setSpan(row, 0, 1, self._settings_model.columnCount())


class SettingsValueDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):  # noqa: N802
        editor_type = index.data(Qt.ItemDataRole.UserRole)
        options = index.data(Qt.ItemDataRole.UserRole + 1) or ()
        if editor_type in {"bool", "choice"}:
            combo = QComboBox(parent)
            if editor_type == "bool":
                combo.addItems(["True", "False"])
            else:
                combo.addItems([str(option) for option in options])
            return combo
        if editor_type == "int":
            spin = QSpinBox(parent)
            minimum, maximum, step = _numeric_options(options, 0, 999999, 1)
            spin.setRange(int(minimum), int(maximum))
            spin.setSingleStep(int(step))
            return spin
        if editor_type == "float":
            spin = QDoubleSpinBox(parent)
            minimum, maximum, step = _numeric_options(options, -999999.0, 999999.0, 0.1)
            spin.setRange(float(minimum), float(maximum))
            spin.setSingleStep(float(step))
            spin.setDecimals(3)
            return spin
        return super().createEditor(parent, option, index)

    def setEditorData(self, editor, index) -> None:  # noqa: N802
        if isinstance(editor, QComboBox):
            value = str(index.data(Qt.ItemDataRole.EditRole) or "")
            row = max(0, editor.findText(value))
            editor.setCurrentIndex(row)
            return
        if isinstance(editor, QSpinBox):
            editor.setValue(int(float(index.data(Qt.ItemDataRole.EditRole) or 0)))
            return
        if isinstance(editor, QDoubleSpinBox):
            editor.setValue(float(index.data(Qt.ItemDataRole.EditRole) or 0))
            return
        super().setEditorData(editor, index)

    def setModelData(self, editor, model, index) -> None:  # noqa: N802
        if isinstance(editor, QComboBox):
            model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)
            return
        if isinstance(editor, QSpinBox):
            model.setData(index, str(editor.value()), Qt.ItemDataRole.EditRole)
            return
        if isinstance(editor, QDoubleSpinBox):
            model.setData(index, str(editor.value()), Qt.ItemDataRole.EditRole)
            return
        super().setModelData(editor, model, index)


def _numeric_options(options, default_min, default_max, default_step):
    values = list(options or ())
    while len(values) < 3:
        values.append(None)
    minimum = default_min if values[0] in (None, "") else values[0]
    maximum = default_max if values[1] in (None, "") else values[1]
    step = default_step if values[2] in (None, "") else values[2]
    return minimum, maximum, step

