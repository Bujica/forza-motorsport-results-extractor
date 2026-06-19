from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUI_ROOT = ROOT / "forza" / "gui"

def test_process_view_does_not_expose_outputs_card() -> None:
    source = (GUI_ROOT / "views" / "process_view.py").read_text(encoding="utf-8")

    for token in (
        "Outputs",
        "Generate PDF + Rebuild",
        "Open last PDF",
        "rebuild_requested",
        "open_pdf_requested",
        "set_rebuild_running",
        "rebuild_button",
        "open_pdf_button",
    ):
        assert token not in source

    assert "Run Config" in source
    assert "Progress" in source
    assert "Event Log" in source


def test_main_window_does_not_wire_process_outputs_actions() -> None:
    source = (GUI_ROOT / "main_window.py").read_text(encoding="utf-8")

    assert "self._process_view.rebuild_requested" not in source
    assert "self._process_view.open_pdf_requested" not in source
    assert "self._process_view.set_rebuild_running" not in source
    assert "self._best_laps_view.open_pdf_requested.connect(self._rebuild_controller.open_last_pdf)" in source
