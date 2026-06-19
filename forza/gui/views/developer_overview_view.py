from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..widgets.card import make_card
from ..widgets.status_badge import StatusBadge


class DeveloperOverviewView(QWidget):
    refresh_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addLayout(self._build_toolbar())
        root.addWidget(self._build_status_grid())
        root.addStretch(1)

    def _build_toolbar(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.loading_label = QLabel("")
        self.loading_label.setObjectName("mutedLabel")
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self._emit_refresh)
        layout.addWidget(self.loading_label, 1)
        layout.addWidget(self.refresh_button)
        return layout

    def _build_status_grid(self) -> QFrame:
        card = make_card()
        layout = QGridLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        self.lm_badge = StatusBadge()
        self.lm_text = _value_label("Not checked")
        self.lm_endpoint_text = _value_label("—")
        self.lm_model_text = _value_label("—")
        self.lm_instance_text = _value_label("—")
        self.lm_configured_load_text = _value_label("—")
        self.lm_configured_request_text = _value_label("—")
        self.lm_configured_image_text = _value_label("—")
        self.lm_runtime_policy_text = _value_label("—")
        self.lm_loaded_runtime_text = _value_label("—")
        self.lm_capabilities_text = _value_label("—")
        self.lm_info_text = _value_label("—")
        self.lm_warnings_text = _value_label("—")
        self.db_badge = StatusBadge()
        self.db_text = _value_label("Not checked")
        self.schema_text = _value_label("—")
        self.inventory_text = _value_label("—")
        self.review_text = _value_label("—")
        layout.addWidget(QLabel("LM Studio"), 0, 0)
        layout.addWidget(self.lm_badge, 0, 1)
        layout.addWidget(self.lm_text, 0, 2)
        layout.addWidget(QLabel("Endpoint"), 1, 0)
        layout.addWidget(self.lm_endpoint_text, 1, 2)
        layout.addWidget(QLabel("Configured model"), 2, 0)
        layout.addWidget(self.lm_model_text, 2, 2)
        layout.addWidget(QLabel("Loaded instance"), 3, 0)
        layout.addWidget(self.lm_instance_text, 3, 2)
        layout.addWidget(QLabel("Configured load"), 4, 0)
        layout.addWidget(self.lm_configured_load_text, 4, 2)
        layout.addWidget(QLabel("Configured request"), 5, 0)
        layout.addWidget(self.lm_configured_request_text, 5, 2)
        layout.addWidget(QLabel("Image request"), 6, 0)
        layout.addWidget(self.lm_configured_image_text, 6, 2)
        layout.addWidget(QLabel("Runtime policy"), 7, 0)
        layout.addWidget(self.lm_runtime_policy_text, 7, 2)
        layout.addWidget(QLabel("Loaded runtime"), 8, 0)
        layout.addWidget(self.lm_loaded_runtime_text, 8, 2)
        layout.addWidget(QLabel("Capabilities"), 9, 0)
        layout.addWidget(self.lm_capabilities_text, 9, 2)
        layout.addWidget(QLabel("Model info"), 10, 0)
        layout.addWidget(self.lm_info_text, 10, 2)
        layout.addWidget(QLabel("Warnings"), 11, 0)
        layout.addWidget(self.lm_warnings_text, 11, 2)
        layout.addWidget(QLabel("Database"), 12, 0)
        layout.addWidget(self.db_badge, 12, 1)
        layout.addWidget(self.db_text, 12, 2)
        layout.addWidget(QLabel("Schema"), 13, 0)
        layout.addWidget(self.schema_text, 13, 2)
        layout.addWidget(QLabel("Inventory"), 14, 0)
        layout.addWidget(self.inventory_text, 14, 2)
        layout.addWidget(QLabel("Review"), 15, 0)
        layout.addWidget(self.review_text, 15, 2)
        layout.setColumnStretch(2, 1)
        return card

    def set_loading(self, loading: bool) -> None:
        self.refresh_button.setEnabled(not loading)
        self.loading_label.setText("Refreshing..." if loading else "")

    def show_snapshot(self, snapshot) -> None:
        self.set_loading(False)
        lm_kind = {"ok": "success", "warning": "warning", "error": "danger"}.get(snapshot.lmstudio_level, "neutral")
        self.lm_badge.set_status(snapshot.lmstudio_level, kind=lm_kind)
        self.lm_text.setText(snapshot.lmstudio_message)
        self.lm_endpoint_text.setText(snapshot.lmstudio_endpoint)
        self.lm_model_text.setText(snapshot.lmstudio_model)
        self.lm_instance_text.setText(snapshot.lmstudio_loaded_instance)
        self.lm_configured_load_text.setText(snapshot.lmstudio_configured_load)
        self.lm_configured_request_text.setText(snapshot.lmstudio_configured_request)
        self.lm_configured_image_text.setText(snapshot.lmstudio_configured_image)
        self.lm_runtime_policy_text.setText(snapshot.lmstudio_runtime_policy)
        self.lm_loaded_runtime_text.setText(snapshot.lmstudio_loaded_runtime)
        self.lm_capabilities_text.setText(snapshot.lmstudio_capabilities)
        self.lm_info_text.setText(snapshot.lmstudio_model_info)
        self.lm_warnings_text.setText(snapshot.lmstudio_warnings)
        self.db_badge.set_status("ok" if snapshot.db_ok else "issues", kind="success" if snapshot.db_ok else "warning")
        profile = getattr(snapshot, "db_check_profile", "fast")
        profile_label = "Fast DB checks" if profile == "fast" else "DB Doctor"
        suffix = " Run DB Doctor for full file/hash audit." if profile == "fast" else ""
        self.db_text.setText(
            f"{profile_label}: {snapshot.db_error_count} error(s), {snapshot.db_warning_count} warning(s). "
            f"{snapshot.database_file}.{suffix}"
        )
        self.schema_text.setText(snapshot.schema_state)
        self.inventory_text.setText(
            f"{snapshot.available_images}/{snapshot.images} available image(s)"
        )
        self.review_text.setText(
            f"{snapshot.review_open} open review case(s)"
        )

    def show_error(self, message: str) -> None:
        self.set_loading(False)
        self.db_badge.set_status("error", kind="danger")
        self.db_text.setText(message)

    def _emit_refresh(self) -> None:
        self.set_loading(True)
        self.refresh_requested.emit()


def _value_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    return label
