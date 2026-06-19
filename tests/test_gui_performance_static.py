from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUI_ROOT = ROOT / "forza" / "gui"
APPLICATION_ROOT = ROOT / "forza" / "application"


def test_performance_controller_uses_worker_and_has_no_direct_read_or_analytics() -> None:
    source = (GUI_ROOT / "controllers" / "performance_controller.py").read_text(encoding="utf-8")

    assert "PerformanceWorker" in source
    assert "QThread" in source
    assert "loading_changed = Signal(bool)" in source
    assert "PerformanceWorker(database_file=self._cfg.database_file, gamertag=self._gamertag)" in source
    assert "list_laps()" not in source
    assert "list_external_records(self._reader)" not in source
    assert "def _load_active_community_records" not in source
    assert "database.list_external_records()" not in source
    assert "GuiWriteService" not in source

    for token in (
        "def build_dashboard(",
        "def _records_by_track_class(",
        "def _strongest_tracks(",
        "def _improvement_targets(",
        "def _car_usage(",
        "def _strongest_cars(",
        "def _recent_best_laps(",
        "def _external_gaps(",
        "class PerformanceDashboard",
        "class PerformanceRow",
        "class PerformanceCard",
    ):
        assert token not in source


def test_performance_worker_loads_reader_records_and_builds_dashboard() -> None:
    source = (GUI_ROOT / "workers" / "performance_worker.py").read_text(encoding="utf-8")

    assert "class PerformanceWorker" in source
    assert "finished = Signal(object)" in source
    assert "GuiReadService" in source
    assert "list_external_records(reader)" in source
    assert "build_dashboard(laps, gamertag=gamertag, external_records=external_records)" in source
    assert "reader.close()" in source


def test_performance_service_contains_summary_model_and_car_analysis() -> None:
    source = (APPLICATION_ROOT / "performance_service.py").read_text(encoding="utf-8")

    for token in (
        "class ProgressPoint",
        "class TrackRecord",
        "class RivalRecord",
        "class PerformanceSummary",
        "community_records_loaded",
        "community_records_comparable",
        "community_records_matched",
        "closest_to_community_pct",
        "gap_to_community_pct",
        "gap_to_rival_pct",
        "class CarPerformance",
        "def compute_performance_summary(",
        "def build_car_performance(",
        "i_hold_combo_record",
        "dominant_car",
        "most_used_car",
    ):
        assert token in source

    assert 'race_class.upper() == "TCR"' in source
    assert 'weather != "dry"' in source
    assert "from PySide6" not in source
    assert "DatabaseService" not in source


def test_records_view_uses_track_record_table_filters_and_detail_panel() -> None:
    source = (GUI_ROOT / "views" / "records_view.py").read_text(encoding="utf-8")
    model_source = (GUI_ROOT / "models" / "performance_table_model.py").read_text(encoding="utf-8")

    for token in (
        "RecordsView",
        "TrackRecordTableModel",
        "CarPerformanceTableModel",
        "ProgressTableModel",
        "RivalTableModel",
        "show_dashboard",
        "set_loading",
        "_track_filter",
        "_class_filter",
        "_weather_filter",
        "Community record (Best Laps)",
        "_performance_status",
        "Clear filters",
        "Refresh",
        "Cars in selected combo",
        "Rivals",
        "_show_record_detail",
        "_rivals_from_records",
        "selectionChanged.connect",
    ):
        assert token in source

    for token in (
        "class TrackRecordTableModel",
        "class CarPerformanceTableModel",
        "class ProgressTableModel",
        "class RivalTableModel",
        "Most used car",
        "Dominant car",
        "Community record",
        "Community gap",
        "Best Laps community/external records",
        "no TCR record",
        "not comparable",
        "_duration_from_ms",
        "Combos",
    ):
        assert token in model_source

    assert "Global rivals" not in source
    assert "QTabWidget" not in source
    assert "External Records" not in source
    assert "Import spreadsheet" not in source
    assert "show_external_records" not in source
    assert "_configure_filter_combo" in source
    assert "_configure_filter_combo(self._track_filter, minimum_width=260" in source
    assert "AdjustToMinimumContentsLengthWithIcon" in source
    assert "setSectionResizeMode(QHeaderView.ResizeMode.Interactive)" in source
    assert "resizeColumnsToContents()" in source
    assert "_resize_table_columns" in source


def test_main_window_wires_records_screen() -> None:
    source = (GUI_ROOT / "main_window.py").read_text(encoding="utf-8")

    assert "PerformanceController" in source
    assert "RecordsView" in source
    assert '"records": self._build_records_section' in source
    assert "self._records_view.refresh_requested.connect(self._performance_controller.refresh)" in source
    assert "self._performance_controller.dashboard_changed.connect(self._records_view.show_dashboard)" in source
    assert "self._performance_controller.loading_changed.connect(self._records_view.set_loading)" in source
    assert "self._records_view.import_external_records_requested.connect(self._performance_controller.import_external_records)" not in source
    assert "self._performance_controller.external_records_changed.connect(self._records_view.show_external_records)" not in source
    assert "self._process_controller.event_received.connect(self._handle_runtime_event)" in source
    assert "self._performance_controller.handle_event(event)" in source
    assert "self._controllers" in source
