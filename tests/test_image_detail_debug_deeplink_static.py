from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_image_detail_extractions_tab_selects_specific_debug_result() -> None:
    source = _source("forza/gui/views/image_detail_view.py")

    assert "open_debug_requested = Signal(str)" in source
    assert "self.open_debug_button.clicked.connect(self._emit_open_debug)" in source
    assert 'tabs.addTab(self._build_extractions_tab(), "Extractions")' in source
    assert "def _build_extractions_tab(self) -> QWidget:" in source
    assert "def _set_extractions(self, results) -> None:" in source
    assert "def _on_extraction_selected(self, index) -> None:" in source
    assert "def _emit_open_debug(self) -> None:" in source
    assert "self.open_debug_requested.emit(self._selected_extraction_result_id)" in source
    assert "item.setData(Qt.ItemDataRole.UserRole, result.id)" in source


def test_image_detail_controller_validates_selected_extraction_result_id() -> None:
    source = _source("forza/gui/controllers/image_detail_controller.py")

    assert "def request_open_debug(self, extraction_result_id: str | None = None) -> None:" in source
    assert "if extraction_result_id is not None:" in source
    assert "self.open_debug_requested.emit(extraction_result_id)" in source
    assert "def _latest_extraction_result_id(results) -> str | None:" in source


def test_image_debug_deep_link_selects_matching_result_option() -> None:
    debug_source = _source("forza/gui/views/image_debug_view.py")
    main_source = _source("forza/gui/main_window.py")

    assert "def select_result(self, extraction_result_id: str) -> bool:" in debug_source
    assert "self.result_combo.findData(extraction_result_id)" in debug_source
    assert "self.result_combo.setCurrentIndex(index)" in debug_source

    method = main_source.split("def _show_image_debug_result(self, extraction_result_id: str) -> None:", 1)[1].split("def _mark_sections", 1)[0]
    assert "self._image_debug_controller.load_result(extraction_result_id)" in method
    assert "self._image_debug_view.select_result(extraction_result_id)" in method
