from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUI_ROOT = ROOT / "forza" / "gui"
SERVICES_ROOT = ROOT / "forza" / "application"

def _gui_read_source() -> str:
    return "\n".join(
        (
            (SERVICES_ROOT / "gui_read_service.py").read_text(encoding="utf-8"),
            (SERVICES_ROOT / "gui_read" / "types.py").read_text(encoding="utf-8"),
            (SERVICES_ROOT / "gui_read" / "review_reads.py").read_text(encoding="utf-8"),
        )
    )



def test_gui_read_review_queue_returns_dto_and_supports_filters() -> None:
    source = _gui_read_source()

    assert "class GuiReviewCase" in source
    assert "def list_review_queue(" in source
    assert "status: str | None = \"open\"" in source
    assert "reason: str | None = None" in source
    assert "outcome: str | None = None" in source
    assert "run_id: str | None = None" in source
    assert "return [_review_case(row, _current_review_lap(session, row)) for row in rows]" in source
    assert "business_key: str" in source
    assert "current_best_lap" in source


def test_review_controller_uses_gui_services_not_repositories() -> None:
    source = (GUI_ROOT / "controllers" / "review_controller.py").read_text(encoding="utf-8")

    assert "GuiReadService" in source
    assert "GuiWriteService" in source
    assert "resolve_review_case" in source
    assert "ignore_review_case" in source
    assert "reopen_review_case" in source


def test_review_view_matches_approved_three_panel_layout_and_actions() -> None:
    source = (GUI_ROOT / "views" / "review_queue_view.py").read_text(encoding="utf-8")

    assert "main = QSplitter(Qt.Orientation.Horizontal)" in source
    assert "left = QSplitter(Qt.Orientation.Vertical)" in source
    assert "left.addWidget(self._build_preview_panel())" in source
    assert "left.addWidget(self._build_queue_panel())" in source
    assert "main.addWidget(left)" in source
    assert "main.addWidget(self._build_detail_panel())" in source
    assert "Case Queue" in source
    assert "Image" in source
    assert "Details and Actions" in source
    assert "Resolution" in source
    assert "Outcome" in source
    assert "Trigger" in source
    assert "Decision" in source
    assert "Stable ID" in source
    assert "Model value" in source
    assert "Corrected value" in source
    assert "Current lap" in source
    assert "case.resolution_note" in source
    assert "QTableWidget(0, 6)" in source
    assert "ResizeToContents" in source
    assert "setDefaultSectionSize(24)" in source
    assert "setMinimumHeight(_lap_table_height(self.laps, rows=13))" in source
    assert "def _lap_table_height(table: QTableWidget, *, rows: int)" in source
    assert "QShortcut(QKeySequence(key), self)" in source
    assert "\"Up\", self.previous_requested.emit" in source
    assert "\"Down\", self.next_requested.emit" in source
    assert "\"Left\", lambda: self._select_primary_delta(-1)" in source
    assert "\"Right\", lambda: self._select_primary_delta(1)" in source
    assert "\"Return\", self._activate_primary_action" in source
    assert "Dirty" in source
    assert "Clean" in source
    assert "Apply track" in source
    assert "Apply class" in source
    assert "Apply car" in source
    assert "Apply driver name" in source
    assert "Rain" in source
    assert "Dry" in source
    assert "Enter applies:" in source
    assert "WeatherType" not in source
    assert "Ignore case" in source
    assert "Reopen case" in source
    assert "Image details" in source
    assert "ImagePreview" in source
    assert "Auto override:" not in source


def test_review_filters_refresh_when_changed() -> None:
    source = (GUI_ROOT / "views" / "review_queue_view.py").read_text(encoding="utf-8")
    main_window = (GUI_ROOT / "main_window.py").read_text(encoding="utf-8")
    controller = (GUI_ROOT / "controllers" / "review_controller.py").read_text(encoding="utf-8")

    assert "for combo in (self.status_filter, self.reason_filter, self.outcome_filter, self.run_filter):" in source
    assert "fit_combo_to_contents(combo)" in source
    assert "resize_combo_to_contents(combo)" in source
    assert "filters_changed = Signal(str, object, object, object)" in source
    assert "combo.currentTextChanged.connect(lambda _text: self._emit_filters_changed())" in source
    assert "def _emit_filters_changed" in source
    assert "filters_changed.emit(*self._filter_values())" in source
    assert "self._review_view.filters_changed.connect(self._review_controller.apply_filters)" in main_window
    assert "def apply_filters(" in controller
    assert "self._apply_current_filters(select_first=True)" in controller
    assert "combo.blockSignals(True)" in source
    assert "def set_run_options" in source
    assert "_combo_value(self.run_filter)" in source


def test_image_preview_uses_qpixmap_scaling_without_database_access() -> None:
    source = (GUI_ROOT / "widgets" / "image_preview.py").read_text(encoding="utf-8")

    assert "QPixmap" in source
    assert "KeepAspectRatio" in source
