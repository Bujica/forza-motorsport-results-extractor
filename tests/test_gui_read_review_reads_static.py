from __future__ import annotations

from pathlib import Path

from forza.application.gui_read.review_reads import GuiReviewReadQueries
from forza.application.gui_read.session_provider import GuiReadSessionProvider


ROOT = Path(__file__).resolve().parents[1]


def test_gui_review_reads_move_review_queue_out_of_service() -> None:
    service_source = (ROOT / "forza" / "application" / "gui_read_service.py").read_text(encoding="utf-8")
    review_source = (ROOT / "forza" / "application" / "gui_read" / "review_reads.py").read_text(encoding="utf-8")

    assert "self._review_reads = GuiReviewReadQueries(self._session_provider)" in service_source
    assert "return self._review_reads.list_review_queue(" in service_source

    moved_tokens = (
        "ReviewCaseEntity.image_file_id == image_file_id",
        'rows = sorted(rows, key=lambda row: (0 if row.outcome == "model_error" else 1, row.created_at))',
        "def _review_case(",
        "def _current_review_lap(",
        "track_suggestions=list(row.track_suggestions_json or [])",
    )
    for token in moved_tokens:
        assert token not in service_source
        assert token in review_source


def test_gui_review_reads_keep_public_service_facade_method() -> None:
    source = (ROOT / "forza" / "application" / "gui_read_service.py").read_text(encoding="utf-8")

    assert "def list_review_queue(" in source
    assert 'status: str | None = "open"' in source
    assert "reason: str | None = None" in source
    assert "outcome: str | None = None" in source
    assert "image_file_id: str | None = None" in source


def test_gui_review_read_queries_public_contract() -> None:
    provider = GuiReadSessionProvider(Path("missing.sqlite"))
    queries = GuiReviewReadQueries(provider)

    assert queries.list_review_queue() == []
