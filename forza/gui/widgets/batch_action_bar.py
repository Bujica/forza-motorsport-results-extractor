from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class BatchActionBar(QWidget):
    process_requested = Signal()
    rename_requested = Signal()
    export_requested = Signal()
    delete_requested = Signal()
    rescan_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.selection_label = QLabel("0 selected")
        self.selection_label.setObjectName("mutedLabel")
        layout.addWidget(self.selection_label)
        layout.addStretch(1)

        self.process_button = QPushButton("Process selected")
        self.process_button.clicked.connect(self.process_requested)
        self.rename_button = QPushButton("Rename")
        self.rename_button.clicked.connect(self.rename_requested)
        self.export_button = QPushButton("Export")
        self.export_button.clicked.connect(self.export_requested)
        self.rescan_button = QPushButton("Rescan selected")
        self.rescan_button.clicked.connect(self.rescan_requested)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete_requested)
        layout.addWidget(self.process_button)
        layout.addWidget(self.rename_button)
        layout.addWidget(self.export_button)
        layout.addWidget(self.rescan_button)
        layout.addWidget(self.delete_button)
        self.set_selection_count(0)

    def set_selection_count(self, count: int) -> None:
        self.selection_label.setText(f"{count} selected")
        self._set_enabled(count > 0)

    def set_selection(self, images: list[object]) -> None:
        self.set_selection_count(len(images))

    def _set_enabled(self, enabled: bool) -> None:
        for widget in (
            self.rename_button,
            self.process_button,
            self.export_button,
            self.rescan_button,
            self.delete_button,
        ):
            widget.setEnabled(enabled)
