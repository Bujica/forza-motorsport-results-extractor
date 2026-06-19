from __future__ import annotations

from pathlib import Path

from forza.application.gui_read.artifact_reads import GuiArtifactReadQueries
from forza.application.gui_read.session_provider import GuiReadSessionProvider


ROOT = Path(__file__).resolve().parents[1]


def test_gui_artifact_reads_move_registered_artifact_reads_out_of_service() -> None:
    service_source = (ROOT / "forza" / "application" / "gui_read_service.py").read_text(encoding="utf-8")
    artifact_source = (ROOT / "forza" / "application" / "gui_read" / "artifact_reads.py").read_text(encoding="utf-8")
    image_debug_source = (ROOT / "forza" / "application" / "gui_read" / "image_debug_reads.py").read_text(encoding="utf-8")

    assert "self._artifact_reads = GuiArtifactReadQueries(self._session_provider)" in service_source
    assert "return self._artifact_reads.read_registered_artifact_text(" in service_source

    moved_tokens = (
        "def _canonical_artifact(",
        "def _read_text_file(",
        "def _is_under_any(",
        "def _normalise_raw_response_roots(",
        "ModelArtifactEntity.artifact_type == artifact_type",
    )
    for token in moved_tokens:
        assert token not in service_source
        assert token in artifact_source

    assert "from .artifact_reads import _read_text_file" in image_debug_source
    assert "def _read_text_file(" not in image_debug_source
    assert "def _is_under_any(" not in image_debug_source


def test_gui_artifact_reads_keep_public_service_facade_method() -> None:
    source = (ROOT / "forza" / "application" / "gui_read_service.py").read_text(encoding="utf-8")

    assert "def read_registered_artifact_text(" in source
    assert "allowed_roots: Sequence[Path]" in source
    assert "artifact_type: str = \"raw_response\"" in source


def test_gui_artifact_read_queries_public_contract() -> None:
    provider = GuiReadSessionProvider(Path("missing.sqlite"))
    queries = GuiArtifactReadQueries(provider)

    assert queries.read_registered_artifact_text("missing", allowed_roots=()) is None
