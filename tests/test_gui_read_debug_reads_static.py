from __future__ import annotations

from pathlib import Path

from forza.application.gui_read.image_debug_reads import GuiImageDebugReadQueries
from forza.application.gui_read.session_provider import GuiReadSessionProvider


ROOT = Path(__file__).resolve().parents[1]


def test_gui_image_debug_reads_move_debug_methods_out_of_service() -> None:
    service_source = (ROOT / "forza" / "application" / "gui_read_service.py").read_text(encoding="utf-8")
    image_debug_source = (ROOT / "forza" / "application" / "gui_read" / "image_debug_reads.py").read_text(encoding="utf-8")

    assert "self._image_debug_reads = GuiImageDebugReadQueries(" in service_source
    assert "return self._image_debug_reads.list_image_debug_cases(" in service_source
    assert "return self._image_debug_reads.get_image_debug_case(" in service_source
    assert "return self._image_debug_reads.get_image_debug_case_by_result(" in service_source

    moved_tokens = (
        "def _cases_for_images(",
        "def _case_for_image(",
        "def _detail_for_image(",
        "def _accepted_or_latest_attempt(",
        "def _canonical_raw_artifact(",
        "_read_text_file(raw_artifact.file_path, raw_response_roots)",
    )
    for token in moved_tokens:
        assert token not in service_source
        assert token in image_debug_source


def test_gui_image_debug_reads_keep_public_service_facade_methods() -> None:
    source = (ROOT / "forza" / "application" / "gui_read_service.py").read_text(encoding="utf-8")

    assert "def list_image_debug_cases(" in source
    assert "def get_image_debug_case(" in source
    assert "def get_image_debug_case_by_result(" in source
    assert "status: str | None = None" in source
    assert "prompt_name: str | None = None" in source
    assert "limit: int = 500" in source


def test_gui_image_debug_read_queries_public_contract() -> None:
    provider = GuiReadSessionProvider(Path("missing.sqlite"))
    queries = GuiImageDebugReadQueries(provider, ())

    assert queries.list_image_debug_cases() == []
    assert queries.get_image_debug_case("missing") is None
    assert queries.get_image_debug_case_by_result("missing") is None
