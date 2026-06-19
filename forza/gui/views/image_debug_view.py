from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTableView,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..models.image_debug_table_model import ImageDebugTableModel
from ..widgets.card import make_card


class ImageDebugView(QWidget):
    refresh_requested = Signal(str, str, str, str, str)
    case_selected = Signal(str)
    result_selected = Signal(str, str)
    open_image_detail_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model = ImageDebugTableModel()
        self._cases = []
        self._current_image_file_id: str | None = None
        self._selected_result_id: str | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        root.addWidget(self._build_filter_bar())
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._build_table_panel())
        splitter.addWidget(self._build_detail_panel())
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([280, 720])
        root.addWidget(splitter, 1)

    def _build_filter_bar(self) -> QFrame:
        card = make_card()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        self.status_filter = QComboBox(); self.status_filter.addItems(["all", "ok", "error", "pending", "running", "cancelled"])
        self.backend_filter = QComboBox(); self.backend_filter.addItem("all")
        self.model_filter = QComboBox(); self.model_filter.addItem("all")
        self.prompt_filter = QComboBox(); self.prompt_filter.addItem("all")
        self.run_filter = QComboBox(); self.run_filter.addItem("all")
        for label, combo in (("Status", self.status_filter), ("Backend", self.backend_filter), ("Model", self.model_filter), ("Prompt", self.prompt_filter), ("Run", self.run_filter)):
            layout.addWidget(QLabel(label)); layout.addWidget(combo)
        layout.addStretch(1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self._emit_refresh)
        layout.addWidget(self.refresh_button)
        for combo in (self.status_filter, self.backend_filter, self.model_filter, self.prompt_filter, self.run_filter):
            combo.currentTextChanged.connect(lambda _text: self._emit_refresh())
        return card

    def _build_table_panel(self) -> QFrame:
        card = make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        title = QLabel("Debug cases")
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        self.table = QTableView()
        self.table.setModel(self._model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.clicked.connect(self._on_table_clicked)
        layout.addWidget(self.table, 1)
        return card

    def _build_detail_panel(self) -> QFrame:
        card = make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        header = QHBoxLayout()
        self.detail_title = QLabel("Image Debug")
        self.detail_title.setObjectName("cardTitle")
        self.result_combo = QComboBox()
        self.result_combo.currentIndexChanged.connect(self._on_result_combo_changed)
        self.open_image_button = QPushButton("Image details")
        self.open_image_button.clicked.connect(self._emit_open_image_detail)
        self.open_image_button.setEnabled(False)
        header.addWidget(self.detail_title, 1)
        header.addWidget(QLabel("Result"))
        header.addWidget(self.result_combo)
        header.addWidget(self.open_image_button)
        layout.addLayout(header)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._text_tab("overview_text", wrap=True), "Overview")
        self.tabs.addTab(self._text_tab("image_metadata_text"), "Image Metadata")
        self.tabs.addTab(self._text_tab("results_text"), "Extraction Results")
        self.tabs.addTab(self._text_tab("attempts_text"), "Attempts")
        self.tabs.addTab(self._text_tab("response_text", wrap=True), "Model Response")
        self.tabs.addTab(self._text_tab("parsed_json_text"), "Parsed Data")
        self.tabs.addTab(self._text_tab("laps_reviews_text", wrap=True), "Laps & Reviews")
        self.tabs.addTab(self._text_tab("artifacts_text"), "Artifacts")
        self.tabs.addTab(self._text_tab("runtime_text"), "Runtime")
        self.tabs.addTab(self._text_tab("timeline_text", wrap=True), "Timeline")
        layout.addWidget(self.tabs, 1)
        return card

    def _text_tab(self, attr_name: str, *, wrap: bool = False) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        text = QTextEdit()
        text.setReadOnly(True)
        mode = QTextEdit.LineWrapMode.WidgetWidth if wrap else QTextEdit.LineWrapMode.NoWrap
        text.setLineWrapMode(mode)
        setattr(self, attr_name, text)
        layout.addWidget(text, 1)
        return page

    def set_cases(self, cases: list[object]) -> None:
        self._cases = list(cases)
        self._model.set_cases(self._cases)
        self.table.resizeColumnsToContents()
        self._sync_filter_options(self._cases)
        if self._cases:
            self.table.selectRow(0)
            first = self._cases[0]
            self._current_image_file_id = first.image_file_id
            self.case_selected.emit(first.image_file_id)
        else:
            self.show_error("No image debug cases found.")

    def select_result(self, extraction_result_id: str) -> bool:
        self._selected_result_id = extraction_result_id
        index = self.result_combo.findData(extraction_result_id)
        if index < 0:
            return False
        self.result_combo.setCurrentIndex(index)
        return True

    def show_detail(self, detail) -> None:
        image = detail.image
        self._current_image_file_id = image.id
        self._selected_result_id = detail.selected_result_id
        self.detail_title.setText(image.current_name or image.semantic_name or image.id)
        self.open_image_button.setEnabled(True)
        self._set_result_options(detail)
        self.overview_text.setPlainText(_overview_text(detail))
        self.image_metadata_text.setPlainText(_metadata_text(detail))
        self.results_text.setPlainText(_results_text(detail.results))
        self.attempts_text.setPlainText(_attempts_text(detail.attempts))
        self.response_text.setPlainText(detail.raw_response or "—")
        self.parsed_json_text.setPlainText(_format_json(detail.parsed_result_payload))
        self.laps_reviews_text.setPlainText(_laps_reviews_text(detail))
        self.artifacts_text.setPlainText(_artifacts_text(detail.artifacts))
        self.runtime_text.setPlainText(_runtime_text(detail.runtime_snapshots))
        self.timeline_text.setPlainText("\n".join(detail.timeline) or "—")

    def show_error(self, message: str) -> None:
        self._current_image_file_id = None
        self._selected_result_id = None
        self.open_image_button.setEnabled(False)
        self.detail_title.setText("Image Debug")
        self.result_combo.blockSignals(True)
        self.result_combo.clear()
        self.result_combo.blockSignals(False)
        for attr in (
            "overview_text", "image_metadata_text", "results_text", "attempts_text",
            "response_text", "parsed_json_text", "laps_reviews_text", "artifacts_text",
            "runtime_text", "timeline_text",
        ):
            getattr(self, attr).setPlainText(message)

    def _set_result_options(self, detail) -> None:
        self.result_combo.blockSignals(True)
        self.result_combo.clear()
        for result in detail.results:
            label = f"{result.status} · {result.run_label} · {result.created_at or '—'}"
            self.result_combo.addItem(label, result.id)
        if detail.selected_result_id:
            index = self.result_combo.findData(detail.selected_result_id)
            if index >= 0:
                self.result_combo.setCurrentIndex(index)
        self.result_combo.blockSignals(False)

    def _emit_refresh(self) -> None:
        self.refresh_requested.emit(
            self.status_filter.currentText(),
            self.backend_filter.currentText(),
            self.model_filter.currentText(),
            self.prompt_filter.currentText(),
            _combo_value(self.run_filter),
        )

    def _on_table_clicked(self, index) -> None:
        case = self._model.case_at(index.row())
        if case is not None:
            self._current_image_file_id = case.image_file_id
            self.case_selected.emit(case.image_file_id)

    def _on_result_combo_changed(self, index: int) -> None:
        if index < 0 or self._current_image_file_id is None:
            return
        result_id = self.result_combo.itemData(index)
        if result_id and result_id != self._selected_result_id:
            self.result_selected.emit(self._current_image_file_id, str(result_id))

    def _emit_open_image_detail(self) -> None:
        if self._current_image_file_id is not None:
            self.open_image_detail_requested.emit(self._current_image_file_id)

    def _sync_filter_options(self, cases: list[object]) -> None:
        self._sync_combo(self.backend_filter, [item.backend for item in cases])
        self._sync_combo(self.model_filter, [item.model for item in cases])
        self._sync_combo(self.prompt_filter, [item.prompt_name for item in cases])
        self._sync_combo(self.run_filter, [(item.run_id, item.run_label) for item in cases if item.run_id])

    def _sync_combo(self, combo: QComboBox, values) -> None:
        current = _combo_value(combo) or "all"
        existing = {_combo_item_value(combo, i) for i in range(combo.count())}
        new_unique = sorted(
            {_normalise_option(value) for value in values if value and _normalise_option(value)[0] not in existing},
            key=lambda item: item[1].lower(),
        )
        for option_id, label in new_unique:
            combo.addItem(label, option_id)
        idx = combo.findData(current)
        if idx < 0:
            idx = combo.findText(current)
        if idx >= 0:
            combo.setCurrentIndex(idx)


def _overview_text(detail) -> str:
    image = detail.image
    selected = next((result for result in detail.results if result.id == detail.selected_result_id), None)
    return "\n".join(
        (
            f"Image: {image.current_name or image.id}",
            f"File: {image.file_status} · Process: {image.processing_status} · Best lap: {image.best_lap_status}",
            f"Selected result: {selected.status if selected else '—'}",
            f"Attempts: {len(detail.attempts)} · Laps: {len(detail.laps)} · Reviews: {len(detail.reviews)} · Artifacts: {len(detail.artifacts)}",
            f"Raw evidence: {'present' if detail.raw_response else 'missing'}",
            f"Runtime snapshots: {len(detail.runtime_snapshots)}",
        )
    )


def _metadata_text(detail) -> str:
    image = detail.image
    payload = {
        "id": image.id,
        "current_name": image.current_name,
        "semantic_name": image.semantic_name,
        "current_path": image.current_path,
        "file_hash": image.file_hash,
        "duplicate_of_image_file_id": image.duplicate_of_image_file_id,
        "file_status": image.file_status,
        "processing_status": image.processing_status,
        "best_lap_status": image.best_lap_status,
        "size_bytes": image.file_size_bytes,
        "width_px": image.width_px,
        "height_px": image.height_px,
        "bit_depth": image.bit_depth,
        "color_mode": image.color_mode,
        "mime_type": image.mime_type,
        "image_format": image.image_format,
        "file_modified_at": str(image.file_modified_at or ""),
        "race_datetime": str(image.race_datetime or ""),
        "race_date": str(image.race_date or ""),
        "race_datetime_source": image.race_datetime_source,
        "image_metadata_json": image.image_metadata_json or {},
    }
    return _format_json(payload)


def _results_text(results) -> str:
    if not results:
        return "No extraction results."
    lines = []
    for result in results:
        lines.append(
            f"{result.created_at or '—'} · {result.status} · run={result.run_label} · model={result.model or '—'} · "
            f"prompt={result.prompt_name or '—'} · attempts={result.attempt_count} · duration={result.duration_ms or '—'} ms · "
            f"tokens={result.input_tokens or '—'}/{result.output_tokens or '—'} · error={result.error_message or '—'} · id={result.id}"
        )
    return "\n".join(lines)


def _attempts_text(attempts) -> str:
    if not attempts:
        return "No attempts for the selected result."
    lines = []
    for attempt in attempts:
        accepted = "accepted" if attempt.accepted else attempt.status
        lines.append(
            f"#{attempt.attempt_number} · {accepted} · reason={attempt.attempt_reason} · model={attempt.model or '—'} · "
            f"instance={attempt.model_instance_id or '—'} · runtime={attempt.runtime_snapshot_id or '—'} · "
            f"duration={attempt.duration_ms or '—'} ms · tps={attempt.tokens_per_second or '—'} · "
            f"parse_error={attempt.parse_error or '—'} · validation={attempt.validation_status or '—'}"
        )
    return "\n".join(lines)


def _laps_reviews_text(detail) -> str:
    lines = ["Laps"]
    if detail.laps:
        for lap in detail.laps:
            flags = []
            if lap.dirty:
                flags.append("dirty")
            if lap.is_best_lap:
                flags.append("best")
            lines.append(f"#{lap.lap_index} · {lap.track} · {lap.race_class} · {lap.driver} · {lap.car} · {lap.best_lap} · {'/'.join(flags) or 'clean'}")
    else:
        lines.append("No laps.")
    lines.append("")
    lines.append("Reviews")
    if detail.reviews:
        for review in detail.reviews:
            lines.append(
                f"#{review.case_number} · {review.status} · {review.reason} · outcome={review.outcome} · "
                f"field={review.decision_field or '—'} · model={review.model_value or '—'} · corrected={review.corrected_value or '—'}"
            )
    else:
        lines.append("No review cases.")
    return "\n".join(lines)


def _artifacts_text(artifacts) -> str:
    if not artifacts:
        return "No registered artifacts."
    return "\n".join(
        f"{artifact.artifact_type} · canonical={artifact.is_canonical} · size={artifact.size_bytes} · sha256={artifact.sha256} · path={artifact.relative_path or artifact.file_path}"
        for artifact in artifacts
    )


def _runtime_text(snapshots) -> str:
    if not snapshots:
        return "No runtime snapshot linked."
    return "\n\n".join(
        _format_json(
            {
                "id": snapshot.id,
                "run_id": snapshot.run_id,
                "kind": snapshot.snapshot_kind,
                "endpoint": snapshot.endpoint,
                "configured_model": snapshot.configured_model,
                "matched_model": snapshot.matched_model,
                "loaded_model": snapshot.loaded_model,
                "instance_id": snapshot.instance_id,
                "display_name": snapshot.display_name,
                "architecture": snapshot.architecture,
                "format": snapshot.format,
                "params": snapshot.params_string,
                "quantization": snapshot.quantization,
                "max_context_length": snapshot.max_context_length,
                "health_ok": snapshot.health_ok,
                "health_message": snapshot.health_message,
                "model_matches_config": snapshot.model_matches_config,
                "desired_load_config_json": snapshot.desired_load_config_json,
                "effective_load_config_json": snapshot.effective_load_config_json,
                "capabilities_json": snapshot.capabilities_json,
                "captured_at": str(snapshot.captured_at or ""),
            }
        )
        for snapshot in snapshots
    )


def _format_json(value) -> str:
    if not value:
        return "—"
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)


def _combo_value(combo: QComboBox) -> str:
    data = combo.currentData()
    return str(data) if data is not None else combo.currentText()


def _combo_item_value(combo: QComboBox, index: int) -> str:
    data = combo.itemData(index)
    return str(data) if data is not None else combo.itemText(index)


def _normalise_option(value) -> tuple[str, str]:
    if isinstance(value, tuple) and len(value) == 2:
        return str(value[0]), str(value[1])
    option_id = getattr(value, "id", value)
    label = getattr(value, "label", value)
    return str(option_id), str(label)
