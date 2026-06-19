from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints

from forza.gui.controllers.best_laps_controller import (
    BestLapRow,
    BestLapsController,
    _csv_row,
    _export_lap,
    _external_pdf_row,
    _row_from_external,
)


ROOT = Path(__file__).resolve().parents[1]
GUI_ROOT = ROOT / "forza" / "gui"


def test_best_laps_controller_uses_gui_read_service_path() -> None:
    source = (GUI_ROOT / "controllers" / "best_laps_controller.py").read_text(encoding="utf-8")
    helper = (ROOT / "forza" / "application" / "gui_read_service_best_laps.py").read_text(encoding="utf-8")

    assert "GuiReadService" in source
    assert "BestLapService" not in source
    assert "list_laps(best_only=True)" in source
    assert "list_external_records(self._reader)" in source
    assert "ordered_lap_key(row, {})" in source
    assert "cfg.database_file" in source
    assert "image_file_id" in source
    assert "lap_id" in source
    assert "GuiWriteService" not in source
    assert "ExternalRecordRepository" in helper
    assert "GuiReadService" in helper


def test_best_laps_controller_imports_external_records_and_reloads_table() -> None:
    source = (GUI_ROOT / "controllers" / "best_laps_controller.py").read_text(encoding="utf-8")

    assert "ExternalRecordService" in source
    assert "def import_external_records" in source
    assert "import_to_db(database, path)" in source
    assert "self.reload()" in source
    assert "external_records_imported" in source
    assert "_external_import_message" in source


def test_best_laps_pdf_rows_preserve_internal_and_external_export_contracts() -> None:
    internal = _best_lap_row(race_class="TCR", driver="Ana", car="Audi RS 3")
    external = _best_lap_row(race_class="A", driver="External", car="Meta Car", is_external=True)

    export_lap = _export_lap(internal)
    external_row = _external_pdf_row(external)

    assert export_lap.image_file_id == "image"
    assert export_lap.source_file == "source.png"
    assert export_lap.track == "Track"
    assert export_lap.race_class == "TCR"
    assert export_lap.weather == "dry"
    assert export_lap.temp_f == 70.0
    assert export_lap.temp_c == 21.1
    assert export_lap.driver == "Ana"
    assert export_lap.car == "Audi RS 3"
    assert export_lap.car_class == "TCR"
    assert export_lap.best_lap == "1:23.456"
    assert export_lap.best_lap_ms == 83456
    assert export_lap.dirty is False
    assert export_lap.is_best_lap is True

    assert external_row == {
        "track": "Track",
        "race_class": "A",
        "driver": "External",
        "car": "Meta Car",
        "best_lap": "1:23.456",
        "best_lap_ms": 83456,
        "source": "External",
    }


def test_best_laps_csv_row_preserves_displayed_row_identity_fields() -> None:
    row = _best_lap_row(race_class="TCR", driver="Ana", car="Audi RS 3")

    csv_row = _csv_row(row)

    assert csv_row == {
        "track": "Track",
        "race_class": "TCR",
        "weather": "dry",
        "temp_f": 70.0,
        "driver": "Ana",
        "car": "Audi RS 3",
        "car_class": "TCR",
        "best_lap": "1:23.456",
        "best_lap_ms": 83456,
        "dirty": False,
        "source": "source.png",
        "source_type": "internal",
        "source_file": "source.png",
        "image_file_id": "image",
        "lap_id": "lap",
        "run_id": "run",
    }


def test_best_laps_controller_builds_cascading_filter_options_from_cached_rows() -> None:
    source = (GUI_ROOT / "controllers" / "best_laps_controller.py").read_text(encoding="utf-8")

    assert "self._all_rows" in source
    assert "self._loaded" in source
    assert "def reload" in source
    assert "def apply_filters" in source
    assert "self._all_rows = sorted(rows, key=lambda row: ordered_lap_key(row, {}))" in source
    assert "self.filter_options_changed.emit(self._filter_options(self._all_rows))" in source
    assert "if not self._loaded:" in source
    assert "exclude=\"driver\"" in source
    assert "exclude=\"car\"" in source
    assert "dirty_states" in source
    assert "source_states" in source
    assert "exclude=\"source\"" in source


def test_best_laps_filter_options_are_limited_by_active_filters() -> None:
    controller = BestLapsController.__new__(BestLapsController)
    controller._track = None
    controller._race_class = "TCR"
    controller._weather = None
    controller._driver = None
    controller._car = None
    controller._dirty = "all"
    controller._source = "all"
    controller._gamertag = "ana"
    controller._only_mine = False

    options = controller._filter_options([
        _best_lap_row(race_class="TCR", driver="Ana", car="Audi RS 3"),
        _best_lap_row(race_class="TCR", driver="Bruno", car="Honda Civic"),
        _best_lap_row(race_class="A", driver="Carlos", car="Porsche 911"),
    ])

    assert options.drivers == ["Ana", "Bruno"]
    assert options.cars == ["Audi RS 3", "Honda Civic"]
    assert options.race_classes == ["A", "TCR"]
    assert options.source_states == ["screenshots"]


def test_best_laps_only_this_driver_is_independent_from_source_filter() -> None:
    controller = BestLapsController.__new__(BestLapsController)
    controller._track = None
    controller._race_class = None
    controller._weather = None
    controller._driver = None
    controller._car = None
    controller._dirty = "all"
    controller._source = "all"
    controller._gamertag = "ana"
    controller._only_mine = True

    rows = controller._apply_filters([
        _best_lap_row(race_class="TCR", driver="Ana", car="Audi RS 3"),
        _best_lap_row(race_class="TCR", driver="Bruno", car="Honda Civic"),
    ])

    assert [row.driver for row in rows] == ["Ana"]



def test_best_lap_row_identity_annotations_allow_external_none_values() -> None:
    hints = get_type_hints(BestLapRow)

    assert hints["lap_id"] == str | None
    assert hints["image_file_id"] == str | None
    assert hints["run_id"] == str | None

def test_best_laps_external_rows_use_none_for_absent_internal_identity() -> None:
    row = _row_from_external(SimpleNamespace(
        track="Track",
        race_class="A",
        driver="External",
        car="Meta Car",
        best_lap="1:23.456",
        best_lap_ms=83456,
        source="External",
    ))

    assert row.lap_id is None
    assert row.image_file_id is None
    assert row.run_id is None
    assert _csv_row(row)["lap_id"] == ""
    assert _csv_row(row)["image_file_id"] == ""
    assert _csv_row(row)["run_id"] == ""


def test_best_laps_filter_options_include_external_records() -> None:
    controller = BestLapsController.__new__(BestLapsController)
    controller._track = None
    controller._race_class = None
    controller._weather = None
    controller._driver = None
    controller._car = None
    controller._dirty = "all"
    controller._source = "all"
    controller._gamertag = ""
    controller._only_mine = False

    options = controller._filter_options([
        _best_lap_row(race_class="TCR", driver="Ana", car="Audi RS 3"),
        _best_lap_row(race_class="TCR", driver="External", car="Meta Car", is_external=True),
    ])

    assert options.source_states == ["screenshots", "external"]


def test_best_laps_view_has_required_filters_and_actions() -> None:
    source = (GUI_ROOT / "views" / "best_laps_view.py").read_text(encoding="utf-8")

    for token in (
        "Relational frontier",
        "track_filter",
        "class_filter",
        "weather_filter",
        "driver_filter",
        "car_filter",
        "source_filter",
        "only_mine",
        "Gamertag:",
        "dirty_filter",
        "Import spreadsheet",
        "import_external_records_requested",
        "_choose_external_spreadsheet",
        "Export CSV",
        "Image details",
        "set_filter_options",
        "filters_changed",
        "_emit_filters_changed",
    ):
        assert token in source
    assert "\"mine\"" not in source
    assert "(\"Lap\", self.dirty_filter)" in source
    assert "QLabel(\"Best Laps\")" not in source
    assert "ResizeToContents" in source
    assert "resizeColumnsToContents" not in source
    assert "combo.currentTextChanged.connect(lambda _text: self._emit_filters_changed())" in source
    assert "changed |= self._sync_combo(self.driver_filter" in source
    assert "if changed:" in source


def test_best_laps_table_model_contains_pdf_csv_equivalent_columns() -> None:
    source = (GUI_ROOT / "models" / "best_laps_table_model.py").read_text(encoding="utf-8")

    for token in (
        "Driver",
        "Car",
        "Best Lap",
        "Weather",
        "Temp",
        "Source",
        "CLASS_COLORS",
        "BackgroundRole",
        "#FFF8DC",
        "#D6EAF8",
        "_is_player_row",
        "strip_dirty_symbol",
        "_group_rows",
    ):
        assert token in source
    assert "Seconds" not in source


def test_main_window_wires_best_laps_screen() -> None:
    source = (GUI_ROOT / "main_window.py").read_text(encoding="utf-8")

    assert "BestLapsController" in source
    assert "BestLapsView" in source
    assert "\"best_laps\": self._build_best_laps_section" in source
    assert "self._best_laps_view.refresh_requested.connect(self._best_laps_controller.refresh)" in source
    assert "self._best_laps_view.filters_changed.connect(self._best_laps_controller.apply_filters)" in source
    assert "self._best_laps_view.import_external_records_requested.connect(self._best_laps_controller.import_external_records)" in source
    assert "self._best_laps_view.export_requested.connect(self._best_laps_controller.export_csv)" in source
    assert "self._best_laps_view.generate_pdf_requested.connect(self._best_laps_controller.generate_pdf)" in source
    assert "self._best_laps_view.generate_pdf_requested.connect(self._rebuild_controller.start_rebuild)" not in source
    assert "self._best_laps_view.open_detail_requested.connect(self._show_image_detail)" in source
    assert "self._best_laps_controller.external_records_imported.connect(self._performance_controller.refresh)" in source
    assert "_handle_runtime_event" in source
    assert "self._process_controller.event_received.connect(self._handle_runtime_event)" in source
    assert "_dispatch_event_to_section" in source
    assert "self._best_laps_controller.handle_event(event)" in source
    assert "self._controllers" in source


def test_main_window_reloads_best_laps_from_db_when_section_is_stale() -> None:
    source = (GUI_ROOT / "main_window.py").read_text(encoding="utf-8")

    assert (
        'elif key == "best_laps" and self._best_laps_view is not None:\n'
        '            self._best_laps_controller.reload()'
    ) in source


def _best_lap_row(*, race_class: str, driver: str, car: str, is_external: bool = False) -> BestLapRow:
    return BestLapRow(
        lap_id=None if is_external else "lap",
        image_file_id=None if is_external else "image",
        run_id=None if is_external else "run",
        track="Track",
        race_class=race_class,
        weather="dry",
        temp_f=None if is_external else 70.0,
        driver=driver,
        car=car,
        car_class=race_class,
        best_lap="1:23.456",
        best_lap_ms=83456,
        dirty=False,
        source_file="External" if is_external else "source.png",
        source_type="external" if is_external else "internal",
        source_label="External" if is_external else "source.png",
        is_external=is_external,
    )


def test_best_laps_view_has_no_lower_detail_text_panel() -> None:
    text = (ROOT / "forza" / "gui" / "views" / "best_laps_view.py").read_text(encoding="utf-8")
    assert "QTextEdit" not in text
    assert "self.detail =" not in text
    assert "self.detail.setPlainText" not in text
    assert "layout.addWidget(self.detail)" not in text
    assert 'self.detail_button = QPushButton("Image details")' in text
    assert "generate_pdf_requested = Signal()" in text
    assert "open_pdf_requested = Signal()" in text
