from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_result_context_maps_lives_in_shared_gui_read_helper() -> None:
    service_source = (ROOT / "forza" / "application" / "gui_read_service.py").read_text(encoding="utf-8")
    image_debug_source = (ROOT / "forza" / "application" / "gui_read" / "image_debug_reads.py").read_text(encoding="utf-8")
    context_source = (ROOT / "forza" / "application" / "gui_read" / "context_reads.py").read_text(encoding="utf-8")

    assert "def result_context_maps(" in context_source
    assert "from .gui_read.context_reads import result_context_maps" in service_source
    assert "def result_context_maps(" not in service_source
    assert "def result_context_maps(" not in image_debug_source
