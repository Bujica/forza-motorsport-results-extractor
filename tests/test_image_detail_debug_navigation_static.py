from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_image_detail_open_image_debug_button_uses_selected_extraction_handler() -> None:
    source = _source("forza/gui/views/image_detail_view.py")

    assert "open_debug_requested = Signal(str)" in source
    assert "self.open_debug_button.clicked.connect(self._emit_open_debug)" in source
    assert "self.open_debug_button.clicked.connect(self.open_debug_requested.emit)" not in source
    assert "def _emit_open_debug(self) -> None:" in source
    assert "self.open_debug_requested.emit(self._selected_extraction_result_id)" in source


def test_open_image_debug_navigation_hides_detail_dialog_and_raises_main_window() -> None:
    source = _source("forza/gui/main_window.py")
    method = source.split("def _show_image_debug_result(self, extraction_result_id: str) -> None:", 1)[1].split("def _mark_sections_dirty", 1)[0]

    assert "self._image_detail_dialog.hide()" in method
    assert "self.select_section(\"diagnostics\")" in method
    assert "self._diagnostics_view.select_debug()" in method
    assert "self._image_debug_controller.load_result(extraction_result_id)" in method
    assert "self.showNormal()" in method
    assert "self.raise_()" in method
    assert "self.activateWindow()" in method
    assert method.index("self.select_section(\"diagnostics\")") < method.index("self._image_debug_controller.load_result(extraction_result_id)")
