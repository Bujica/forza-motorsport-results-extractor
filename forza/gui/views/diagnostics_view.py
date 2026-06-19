from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget


class DiagnosticsView(QWidget):
    """Diagnostics workspace with lazy-loaded operational tabs."""

    tab_activated = Signal(str)

    def __init__(
        self,
        *,
        tab_factories: list[tuple[str, str, Callable[[], QWidget]]],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._tab_factories = tab_factories
        self._loaded: dict[str, QWidget] = {}
        self.tabs = QTabWidget()
        self._build_ui()
        if self._tab_factories:
            self._ensure_tab_loaded(0)
            self.tabs.setCurrentIndex(0)
            self.tab_activated.emit(self._tab_factories[0][0])

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        for _key, label, _factory in self._tab_factories:
            container = QWidget()
            layout = QVBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            placeholder = QLabel(f"{label} will load when opened.")
            placeholder.setObjectName("mutedLabel")
            layout.addWidget(placeholder)
            self.tabs.addTab(container, label)
        self.tabs.currentChanged.connect(self._on_current_changed)
        root.addWidget(self.tabs, 1)

    def select_debug(self) -> None:
        self.select_tab("debug")

    def select_logs(self) -> None:
        self.select_tab("logs")

    def select_tab(self, key: str) -> None:
        index = self._index_for_key(key)
        if index is None:
            return
        self._ensure_tab_loaded(index)
        self.tabs.setCurrentIndex(index)
        self.tab_activated.emit(key)

    def loaded_widget(self, key: str) -> QWidget | None:
        return self._loaded.get(key)

    def _on_current_changed(self, index: int) -> None:
        if not 0 <= index < len(self._tab_factories):
            return
        key = self._tab_factories[index][0]
        self._ensure_tab_loaded(index)
        self.tab_activated.emit(key)

    def _ensure_tab_loaded(self, index: int) -> QWidget | None:
        if not 0 <= index < len(self._tab_factories):
            return None
        key, _label, factory = self._tab_factories[index]
        existing = self._loaded.get(key)
        if existing is not None:
            return existing
        widget = factory()
        self._loaded[key] = widget
        container = self.tabs.widget(index)
        layout = container.layout() if container is not None else None
        if layout is None:
            return widget
        while layout.count():
            item = layout.takeAt(0)
            child = item.widget()
            if child is not None:
                child.deleteLater()
        layout.addWidget(widget)
        return widget

    def _index_for_key(self, key: str) -> int | None:
        for index, (candidate, _label, _factory) in enumerate(self._tab_factories):
            if candidate == key:
                return index
        return None
