from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...config import AppConfig
from ..config_state import ConfigChangeSet
from ..models.best_laps_table_model import BestLapsTableModel
from ..widgets.card import make_card
from ..widgets.filter_controls import fit_combo_to_contents, resize_combo_to_contents


class BestLapsView(QWidget):
    refresh_requested = Signal(str, str, str, str, str, str, str, bool)
    filters_changed = Signal(str, str, str, str, str, str, str, bool)
    export_requested = Signal(object)
    import_external_records_requested = Signal(object)
    generate_pdf_requested = Signal()
    open_pdf_requested = Signal()
    open_detail_requested = Signal(str)

    def __init__(self, *, cfg=None, parent=None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._model = _table_model_for(cfg)
        self._rows: list[object] = []
        self._build_ui()

    def on_config_changed(self, cfg: AppConfig, changes: ConfigChangeSet) -> None:
        self._cfg = cfg
        if not changes.affects("pdf", "user.gamertag"):
            return
        self._model = _table_model_for(cfg)
        self._model.set_rows(self._rows)
        self.table.setModel(self._model)
        self.detail_button.setEnabled(False)
        self._update_gamertag_controls()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        root.addWidget(self._build_action_card())
        root.addWidget(self._build_filter_bar())
        root.addWidget(self._build_table_panel(), 1)

    def _build_action_card(self) -> QFrame:
        card = make_card()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        self.banner_text = QLabel("Relational frontier used by PDF and CSV exports.")
        self.banner_text.setObjectName("mutedLabel")
        self.banner_text.setWordWrap(True)
        layout.addWidget(self.banner_text, 1)
        import_records = QPushButton("Import spreadsheet")
        import_records.clicked.connect(self._choose_external_spreadsheet)
        generate = QPushButton("Generate PDF")
        generate.clicked.connect(self.generate_pdf_requested)
        open_pdf = QPushButton("Open last PDF")
        open_pdf.clicked.connect(self.open_pdf_requested)
        export = QPushButton("Export CSV")
        export.clicked.connect(self._choose_export_path)
        layout.addWidget(import_records)
        layout.addWidget(generate)
        layout.addWidget(open_pdf)
        layout.addWidget(export)
        return card

    def _build_filter_bar(self) -> QFrame:
        card = make_card()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        self.track_filter = _combo()
        self.class_filter = _combo()
        self.weather_filter = _combo()
        self.driver_filter = _combo()
        self.car_filter = _combo()
        self.source_filter = _combo()
        self.source_filter.addItems(["screenshots", "external"])
        self.dirty_filter = _combo()
        self.dirty_filter.addItems(["clean", "dirty"])
        self.only_mine = QCheckBox("Only this driver")
        self.gamertag_label = QLabel()
        self.gamertag_label.setObjectName("mutedLabel")
        self._update_gamertag_controls()
        for combo in (
            self.track_filter,
            self.class_filter,
            self.weather_filter,
            self.driver_filter,
            self.car_filter,
            self.source_filter,
            self.dirty_filter,
        ):
            resize_combo_to_contents(combo)
        layout.addWidget(self.gamertag_label)
        layout.addWidget(self.only_mine)
        for label, combo in (
            ("Track", self.track_filter),
            ("Class", self.class_filter),
            ("Weather", self.weather_filter),
            ("Driver", self.driver_filter),
            ("Car", self.car_filter),
            ("Source", self.source_filter),
            ("Lap", self.dirty_filter),
        ):
            layout.addWidget(QLabel(label))
            layout.addWidget(combo)
        layout.addStretch(1)
        for combo in (
            self.track_filter,
            self.class_filter,
            self.weather_filter,
            self.driver_filter,
            self.car_filter,
            self.source_filter,
            self.dirty_filter,
        ):
            combo.currentTextChanged.connect(lambda _text: self._emit_filters_changed())
        self.only_mine.toggled.connect(lambda _checked: self._emit_filters_changed())
        return card

    def _build_table_panel(self) -> QFrame:
        card = make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        header = QHBoxLayout()
        self.count_label = QLabel("0 rows")
        self.count_label.setObjectName("mutedLabel")
        self.detail_button = QPushButton("Image details")
        self.detail_button.setEnabled(False)
        self.detail_button.clicked.connect(self._open_selected_detail)
        header.addWidget(self.count_label, 1)
        header.addWidget(self.detail_button)
        layout.addLayout(header)
        self.table = QTableView()
        self.table.setModel(self._model)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.clicked.connect(self._handle_table_click)
        layout.addWidget(self.table, 1)
        return card

    def set_rows(self, rows: list[object]) -> None:
        self._rows = list(rows)
        self._model.set_rows(self._rows)
        self.count_label.setText(f"{len(self._rows)} rows")
        self.banner_text.setText(_summary(self._rows, only_mine=self.only_mine.isChecked()))
        self.detail_button.setEnabled(False)

    def show_message(self, message: str) -> None:
        self.banner_text.setText(message)

    def set_filter_options(self, options) -> None:
        changed = False
        changed |= self._sync_combo(self.track_filter, getattr(options, "tracks", []))
        changed |= self._sync_combo(self.class_filter, getattr(options, "race_classes", []))
        changed |= self._sync_combo(self.weather_filter, getattr(options, "weather", []))
        changed |= self._sync_combo(self.driver_filter, getattr(options, "drivers", []))
        changed |= self._sync_combo(self.car_filter, getattr(options, "cars", []))
        changed |= self._sync_combo(self.source_filter, getattr(options, "source_states", ["screenshots", "external"]))
        changed |= self._sync_combo(self.dirty_filter, getattr(options, "dirty_states", ["clean", "dirty"]))
        if changed:
            self._emit_filters_changed()

    def _emit_refresh(self) -> None:
        self.refresh_requested.emit(*self._filter_values())

    def _emit_filters_changed(self) -> None:
        self.filters_changed.emit(*self._filter_values())

    def _filter_values(self) -> tuple[str, str, str, str, str, str, str, bool]:
        return (
            self.track_filter.currentText(),
            self.class_filter.currentText(),
            self.weather_filter.currentText(),
            self.driver_filter.currentText(),
            self.car_filter.currentText(),
            self.dirty_filter.currentText(),
            self.source_filter.currentText(),
            self.only_mine.isChecked(),
        )

    def _choose_export_path(self) -> None:
        path, _selected = QFileDialog.getSaveFileName(self, "Export best laps", "best_laps.csv", "CSV (*.csv)")
        if path:
            self.export_requested.emit(Path(path))

    def _choose_external_spreadsheet(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "Import external records",
            str(Path("data/external/DataFM.xlsx")),
            "Spreadsheets (*.xlsx *.csv)",
        )
        if path:
            self.import_external_records_requested.emit(Path(path))

    def _open_selected_detail(self) -> None:
        row = self._model.row_at(self.table.currentIndex().row())
        if row is not None and getattr(row, "image_file_id", ""):
            self.open_detail_requested.emit(row.image_file_id)

    def _handle_table_click(self, index) -> None:
        row = self._model.row_at(index.row())
        self.detail_button.setEnabled(row is not None and bool(getattr(row, "image_file_id", "")))

    def _sync_combo(self, combo: QComboBox, values) -> bool:
        current = combo.currentText() or "all"
        unique = ["all"] + sorted({str(value) for value in values if value})
        next_value = current if current in unique else "all"
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(unique)
        combo.setCurrentText(next_value)
        resize_combo_to_contents(combo)
        combo.blockSignals(False)
        return next_value != current

    def _update_gamertag_controls(self) -> None:
        gamertag = str(getattr(self._cfg, "gamertag", "") or "").strip()
        self.gamertag_label.setText(f"Gamertag: {gamertag or 'not set'}")
        self.only_mine.setEnabled(bool(gamertag))
        if not gamertag:
            self.only_mine.setChecked(False)


def _table_model_for(cfg) -> BestLapsTableModel:
    pdf_cfg = getattr(cfg, "pdf", None)
    return BestLapsTableModel(
        dirty_lap_symbol=getattr(pdf_cfg, "dirty_lap_symbol", "†"),
        show_dirty_lap_symbol=getattr(pdf_cfg, "show_dirty_lap_symbol", True),
        gamertag=getattr(cfg, "gamertag", ""),
    )


def _combo() -> QComboBox:
    combo = fit_combo_to_contents(QComboBox())
    combo.addItem("all")
    return combo


def _summary(rows: list[object], *, only_mine: bool = False) -> str:
    if not rows:
        return "No best laps found. Run the pipeline or adjust filters."
    clean = sum(1 for row in rows if not row.dirty)
    dirty = len(rows) - clean
    tracks = len({row.track for row in rows})
    external = sum(1 for row in rows if getattr(row, "is_external", False))
    screenshots = len(rows) - external
    player = " · Only this driver" if only_mine else ""
    return f"Tracks: {tracks} · Clean: {clean} · Dirty: {dirty} · Screenshots: {screenshots} · External: {external}{player}"
