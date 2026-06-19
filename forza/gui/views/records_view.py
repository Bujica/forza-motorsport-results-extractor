from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...application.performance_service import RivalRecord
from ..models.performance_table_model import (
    CarPerformanceTableModel,
    ProgressTableModel,
    RivalTableModel,
    TrackRecordTableModel,
)
from ..widgets.card import make_card


class RecordsView(QWidget):
    refresh_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._track_model = TrackRecordTableModel()
        self._car_model = CarPerformanceTableModel()
        self._progress_model = ProgressTableModel()
        self._rivals_model = RivalTableModel()
        self._cards: list[QLabel] = []
        self._summary = None
        self._records: list[object] = []
        self._track_filter = QComboBox()
        self._class_filter = QComboBox()
        self._weather_filter = QComboBox()
        self._status_label = QLabel("Performance data has not been loaded.")
        self._detail_title = QLabel("Select a combo")
        self._detail_meta = QLabel("No combo selected.")
        self._detail_rival = QLabel("Rival: —")
        self._detail_community = QLabel("Community record (Best Laps): —")
        self._table = QTableView()
        self._car_table = QTableView()
        self._progress_table = QTableView()
        self._rivals_table = QTableView()
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        self.cards_grid = QGridLayout()
        self.cards_grid.setHorizontalSpacing(12)
        self.cards_grid.setVerticalSpacing(12)
        root.addLayout(self.cards_grid)

        _configure_filter_combo(self._track_filter, minimum_width=260, minimum_contents=28)
        _configure_filter_combo(self._class_filter, minimum_width=120, minimum_contents=10)
        _configure_filter_combo(self._weather_filter, minimum_width=130, minimum_contents=12)

        filter_bar = QFrame()
        filters = QGridLayout(filter_bar)
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setHorizontalSpacing(10)
        filters.setVerticalSpacing(8)
        filters.addWidget(QLabel("Track"), 0, 0)
        filters.addWidget(self._track_filter, 0, 1)
        filters.addWidget(QLabel("Class"), 0, 2)
        filters.addWidget(self._class_filter, 0, 3)
        filters.addWidget(QLabel("Weather"), 0, 4)
        filters.addWidget(self._weather_filter, 0, 5)
        filters.setColumnStretch(1, 4)
        filters.setColumnStretch(3, 1)
        filters.setColumnStretch(5, 1)

        clear_button = QPushButton("Clear filters")
        refresh_button = QPushButton("Refresh")
        clear_button.setMinimumWidth(120)
        refresh_button.setMinimumWidth(96)
        filters.addWidget(clear_button, 0, 6)
        filters.addWidget(refresh_button, 0, 7)
        root.addWidget(filter_bar)

        self._status_label.setObjectName("mutedLabel")
        root.addWidget(self._status_label)

        self._table.setModel(self._track_model)
        _configure_table(self._table, minimum_height=240)
        selection_model = self._table.selectionModel()
        if selection_model is not None:
            selection_model.selectionChanged.connect(lambda *_args: self._show_selected_record())
        root.addWidget(self._table, 1)

        detail_row = QHBoxLayout()
        detail_row.setSpacing(12)
        detail_row.addWidget(self._build_combo_detail_card(), 3)
        detail_row.addWidget(self._build_rivals_card(), 2)
        root.addLayout(detail_row)

        self._track_filter.currentTextChanged.connect(self._apply_filters)
        self._class_filter.currentTextChanged.connect(self._apply_filters)
        self._weather_filter.currentTextChanged.connect(self._apply_filters)
        clear_button.clicked.connect(self._clear_filters)
        refresh_button.clicked.connect(self.refresh_requested.emit)

    def _build_combo_detail_card(self) -> QFrame:
        frame = make_card()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        self._detail_title.setObjectName("cardTitle")
        self._detail_meta.setObjectName("mutedLabel")
        self._detail_rival.setObjectName("mutedLabel")
        self._detail_community.setObjectName("mutedLabel")
        for label in (self._detail_meta, self._detail_rival, self._detail_community):
            label.setWordWrap(True)
        layout.addWidget(QLabel("Selected combo"))
        layout.addWidget(self._detail_title)
        layout.addWidget(self._detail_meta)
        layout.addWidget(self._detail_rival)
        layout.addWidget(self._detail_community)
        layout.addWidget(QLabel("Cars in selected combo"))
        self._car_table.setModel(self._car_model)
        _configure_table(self._car_table, minimum_height=150)
        layout.addWidget(self._car_table)
        layout.addWidget(QLabel("Progress"))
        self._progress_table.setModel(self._progress_model)
        _configure_table(self._progress_table, minimum_height=120)
        layout.addWidget(self._progress_table)
        return frame

    def _build_rivals_card(self) -> QFrame:
        frame = make_card()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        title = QLabel("Rivals")
        title.setObjectName("cardTitle")
        subtitle = QLabel("Drivers matching the active Records filters.")
        subtitle.setObjectName("mutedLabel")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        self._rivals_table.setModel(self._rivals_model)
        _configure_table(self._rivals_table, minimum_height=260)
        layout.addWidget(self._rivals_table)
        return frame

    def show_dashboard(self, dashboard) -> None:
        self._set_cards(dashboard.cards)
        self._summary = getattr(dashboard, "summary", None)
        records = list(getattr(self._summary, "track_records", []) or [])
        self._records = records
        self._track_model.set_records(records)
        self._set_filter_options(records)
        self._resize_table_columns()
        self._resize_detail_columns()
        if records:
            self._status_label.setText(_performance_status(records, self._summary))
        else:
            self._status_label.setText("No player clean laps available for Performance.")

    def set_loading(self, loading: bool) -> None:
        if loading:
            self._status_label.setText("Loading performance dashboard…")

    def _set_cards(self, cards: list[object]) -> None:
        while self.cards_grid.count():
            item = self.cards_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for index, card in enumerate(cards):
            self.cards_grid.addWidget(_metric_card(card), index // 5, index % 5)

    def _set_filter_options(self, records: list[object]) -> None:
        current_track = self._track_filter.currentText()
        current_class = self._class_filter.currentText()
        current_weather = self._weather_filter.currentText()
        _set_combo_items(self._track_filter, sorted({record.track for record in records}), current_track)
        _set_combo_items(self._class_filter, sorted({record.race_class for record in records}), current_class)
        _set_combo_items(self._weather_filter, sorted({record.weather for record in records}), current_weather)
        self._apply_filters()

    def _apply_filters(self) -> None:
        track = _filter_value(self._track_filter)
        race_class = _filter_value(self._class_filter)
        weather = _filter_value(self._weather_filter)
        self._track_model.set_filters(
            track=track,
            race_class=race_class,
            weather=weather,
        )
        filtered_records = _filtered_records(
            self._records,
            track=track,
            race_class=race_class,
            weather=weather,
        )
        self._rivals_model.set_rows(_rivals_from_records(filtered_records))
        self._resize_table_columns()
        self._select_first_record()

    def _clear_filters(self) -> None:
        with QSignalBlocker(self._track_filter), QSignalBlocker(self._class_filter), QSignalBlocker(self._weather_filter):
            self._track_filter.setCurrentText("All")
            self._class_filter.setCurrentText("All")
            self._weather_filter.setCurrentText("All")
        self._apply_filters()

    def _select_first_record(self) -> None:
        if self._track_model.rowCount() <= 0:
            self._show_record_detail(None)
            return
        self._table.selectRow(0)
        self._show_record_detail(self._track_model.record_at(0))

    def _show_selected_record(self) -> None:
        index = self._table.currentIndex()
        record = self._track_model.record_at(index.row()) if index.isValid() else None
        self._show_record_detail(record)

    def _show_record_detail(self, record) -> None:
        if record is None:
            self._detail_title.setText("Select a combo")
            self._detail_meta.setText("No combo selected.")
            self._detail_rival.setText("Rival: —")
            self._detail_community.setText("Community record (Best Laps): —")
            self._car_model.set_rows([])
            self._progress_model.set_rows([], best_ms=None)
            return
        self._detail_title.setText(f"{record.track} · {record.race_class} · {record.weather}")
        self._detail_meta.setText(
            f"My best {record.my_best_display or '—'} · {record.my_best_car or '—'} · "
            f"{record.sessions_raced} clean context(s)"
        )
        self._detail_rival.setText(
            f"Rival: {record.rival_best_driver or '—'} · {record.rival_best_display or '—'} · "
            f"gap {_gap_text(record.gap_to_rival_ms, getattr(record, 'gap_to_rival_pct', None))}"
        )
        self._detail_community.setText(
            f"Community record (Best Laps): {_community_text(record)} · gap {_gap_text(record.gap_to_community_ms, getattr(record, 'gap_to_community_pct', None))}"
        )
        self._car_model.set_rows(list(record.car_performance))
        self._progress_model.set_rows(list(record.progress), best_ms=record.my_best_ms)
        self._resize_detail_columns()

    def _resize_table_columns(self) -> None:
        self._table.resizeColumnsToContents()
        header = self._table.horizontalHeader()
        minimum_widths = {
            0: 180,
            1: 80,
            2: 90,
            3: 96,
            4: 170,
            5: 96,
            6: 170,
            7: 120,
            8: 190,
            9: 190,
            10: 80,
            11: 110,
        }
        for column, width in minimum_widths.items():
            if column < self._track_model.columnCount():
                header.resizeSection(column, max(header.sectionSize(column), width))

    def _resize_detail_columns(self) -> None:
        for table in (self._car_table, self._progress_table, self._rivals_table):
            table.resizeColumnsToContents()


def _performance_status(records: list[object], summary: object | None) -> str:
    combo_count = len(records)
    matched = int(getattr(summary, "community_records_matched", 0) or 0)
    comparable = int(getattr(summary, "community_records_comparable", 0) or 0)
    loaded = int(getattr(summary, "community_records_loaded", 0) or 0)
    if comparable <= 0:
        return f"{combo_count} track/class/weather combo(s). No Best Laps community records loaded."
    return (
        f"{combo_count} track/class/weather combo(s). "
        f"Best Laps community records: {matched}/{comparable} matched here, {loaded} loaded total; "
        "dry non-TCR only."
    )


def _metric_card(card) -> QFrame:
    frame = make_card()
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    title = QLabel(card.title)
    title.setObjectName("mutedLabel")
    value = QLabel(card.value)
    value.setObjectName("cardTitle")
    detail = QLabel(card.detail)
    detail.setObjectName("mutedLabel")
    detail.setWordWrap(True)
    layout.addWidget(title)
    layout.addWidget(value)
    layout.addWidget(detail)
    return frame


def _configure_table(table: QTableView, *, minimum_height: int) -> None:
    table.setAlternatingRowColors(True)
    table.setSortingEnabled(True)
    table.setWordWrap(False)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setMinimumHeight(minimum_height)
    table.verticalHeader().setVisible(False)
    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    header.setMinimumSectionSize(72)
    header.setDefaultSectionSize(130)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)


def _configure_filter_combo(combo: QComboBox, *, minimum_width: int, minimum_contents: int) -> None:
    combo.setMinimumWidth(minimum_width)
    combo.setMinimumContentsLength(minimum_contents)
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


def _set_combo_items(combo: QComboBox, values: list[str], current: str) -> None:
    next_value = current if current in values else "All"
    with QSignalBlocker(combo):
        combo.clear()
        combo.addItem("All")
        combo.addItems(values)
        combo.setCurrentText(next_value)


def _filtered_records(
    records: list[object],
    *,
    track: str | None = None,
    race_class: str | None = None,
    weather: str | None = None,
) -> list[object]:
    filtered = list(records)
    if track is not None:
        filtered = [record for record in filtered if getattr(record, "track", None) == track]
    if race_class is not None:
        filtered = [record for record in filtered if getattr(record, "race_class", None) == race_class]
    if weather is not None:
        filtered = [record for record in filtered if getattr(record, "weather", None) == weather]
    return filtered


def _rivals_from_records(records: list[object]) -> list[RivalRecord]:
    by_driver: dict[str, list[object]] = defaultdict(list)
    for record in records:
        driver = str(getattr(record, "rival_best_driver", "") or "").strip()
        if driver:
            by_driver[driver].append(record)

    rivals: list[RivalRecord] = []
    for driver, driver_records in by_driver.items():
        their_best_values = [
            int(value)
            for value in (getattr(record, "rival_best_ms", None) for record in driver_records)
            if value is not None
        ]
        my_best_values = [
            int(value)
            for value in (getattr(record, "my_best_ms", None) for record in driver_records)
            if value is not None
        ]
        faster = sum(
            1
            for record in driver_records
            if getattr(record, "gap_to_rival_ms", None) is not None
            and int(getattr(record, "gap_to_rival_ms")) > 0
        )
        rivals.append(
            RivalRecord(
                driver=driver,
                sessions_shared=len(driver_records),
                their_best_ms=min(their_best_values) if their_best_values else None,
                my_best_in_common_ms=min(my_best_values) if my_best_values else None,
                tracks_shared=sorted({str(getattr(record, "track", "") or "") for record in driver_records}),
                usually_faster=bool(driver_records and faster > len(driver_records) / 2),
            )
        )
    return sorted(rivals, key=lambda row: (-row.sessions_shared, row.driver.lower()))


def _filter_value(combo: QComboBox) -> str | None:
    value = combo.currentText()
    return None if value == "All" else value


def _gap_text(ms: int | None, pct: float | None = None) -> str:
    if ms is None:
        return "—"
    sign = "+" if ms > 0 else ""
    seconds = f"{sign}{ms / 1000:.3f}s"
    if pct is None:
        return seconds
    pct_sign = "+" if pct > 0 else ""
    return f"{seconds} ({pct_sign}{pct:.2f}%)"


def _community_text(record) -> str:
    if str(record.weather).lower() != "dry":
        return "not comparable"
    if str(record.race_class).upper() == "TCR":
        return "no TCR record"
    if record.community_display is None:
        return "no data"
    return f"{record.community_display} · {record.community_driver or '—'} · {record.community_car or '—'}"
