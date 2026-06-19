from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUI_ROOT = ROOT / "forza" / "gui"
SERVICES_ROOT = ROOT / "forza" / "application"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _gui_read_source() -> str:
    return "\n".join(
        (
            _source(SERVICES_ROOT / "gui_read_service.py"),
            _source(SERVICES_ROOT / "gui_read" / "types.py"),
            _source(SERVICES_ROOT / "gui_read" / "image_debug_reads.py"),
        )
    )


def _token(*parts: str) -> str:
    return "".join(parts)


def test_image_debug_replaces_legacy_surface() -> None:
    assert not (GUI_ROOT / "views" / _token("model_", "debug_view.py")).exists()
    assert not (GUI_ROOT / "controllers" / _token("model_", "debug_controller.py")).exists()
    assert not (GUI_ROOT / "models" / _token("model_", "debug_table_model.py")).exists()
    assert (GUI_ROOT / "views" / "image_debug_view.py").exists()
    assert (GUI_ROOT / "controllers" / "image_debug_controller.py").exists()
    assert (GUI_ROOT / "models" / "image_debug_table_model.py").exists()


def test_gui_read_facade_exposes_image_debug_payload() -> None:
    source = _gui_read_source()

    assert "class GuiImageDebugSummary" in source
    assert "class GuiImageDebugDetail" in source
    assert "class GuiImageDebugExtraction" in source
    assert "class GuiImageDebugAttempt" in source
    assert "class GuiImageDebugArtifact" in source
    assert "class GuiImageDebugRuntime" in source
    assert "list_image_debug_cases" in source
    assert "get_image_debug_case" in source
    assert "get_image_debug_case_by_result" in source
    assert "image_metadata_json" in source
    assert "_read_text_file(raw_artifact.file_path, raw_response_roots)" in source
    assert "_parse_raw_json(attempt.raw_response)" in source


def test_image_debug_review_mapping_uses_persisted_review_case_fields() -> None:
    source = _source(SERVICES_ROOT / "gui_read" / "image_debug_reads.py")

    assert "current_track=row.track" in source
    assert "current_race_class=row.race_class" in source
    assert "current_best_lap=row.best_lap" in source
    assert "row.current_track" not in source
    assert "row.current_race_class" not in source
    assert "row.current_best_lap" not in source


def test_image_debug_controller_uses_gui_read_facade_only() -> None:
    source = _source(GUI_ROOT / "controllers" / "image_debug_controller.py")

    assert "GuiReadService" in source
    assert "list_image_debug_cases" in source
    assert "get_image_debug_case" in source
    assert "get_image_debug_case_by_result" in source
    assert "select_image" in source
    assert "select_result" in source
    assert "cases_changed" in source
    assert "detail_loaded" in source
    assert "GuiWriteService" not in source


def test_image_debug_uses_top_bottom_split_for_wide_detail_cards() -> None:
    source = _source(GUI_ROOT / "views" / "image_debug_view.py")

    assert "QSplitter(Qt.Orientation.Vertical)" in source
    assert "splitter.setChildrenCollapsible(False)" in source
    assert "splitter.setSizes([280, 720])" in source


def test_image_debug_view_contains_image_centric_tabs_and_filters() -> None:
    source = _source(GUI_ROOT / "views" / "image_debug_view.py")

    for token in (
        "Image Debug",
        "Debug cases",
        "status_filter",
        "backend_filter",
        "model_filter",
        "prompt_filter",
        "run_filter",
        "Overview",
        "Image Metadata",
        "Extraction Results",
        "Attempts",
        "Model Response",
        "Parsed Data",
        "Laps & Reviews",
        "Artifacts",
        "Runtime",
        "Timeline",
        "Image details",
        "result_combo",
        "select_result",
        "show_detail",
    ):
        assert token in source


def test_main_window_wires_image_debug_inside_diagnostics_and_detail_bridge() -> None:
    source = _source(GUI_ROOT / "main_window.py")

    assert "ImageDebugController" in source
    assert "ImageDebugView" in source
    assert '"diagnostics": self._build_diagnostics_section' in source
    assert "self._image_debug_view.refresh_requested.connect(self._image_debug_controller.refresh)" in source
    assert "self._image_debug_view.case_selected.connect(self._image_debug_controller.select_image)" in source
    assert "self._image_debug_view.result_selected.connect(self._image_debug_controller.select_result)" in source
    assert "self._image_debug_view.open_image_detail_requested.connect(self._show_image_detail)" in source
    assert "self._image_debug_controller.cases_changed.connect(self._image_debug_view.set_cases)" in source
    assert "self._image_debug_controller.detail_loaded.connect(self._image_debug_view.show_detail)" in source
    assert "self._image_detail_controller.open_debug_requested.connect(self._show_image_debug_result)" in source
    assert "self._diagnostics_view.select_debug()" in source
    assert _token("Model", "Debug") not in source
