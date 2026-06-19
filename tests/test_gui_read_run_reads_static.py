from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from forza.application.gui_read.run_reads import GuiRunReadQueries, _run_option
from forza.application.gui_read.session_provider import GuiReadSessionProvider


ROOT = Path(__file__).resolve().parents[1]


def test_gui_run_reads_move_run_methods_out_of_service() -> None:
    service_source = (ROOT / "forza" / "application" / "gui_read_service.py").read_text(encoding="utf-8")
    run_source = (ROOT / "forza" / "application" / "gui_read" / "run_reads.py").read_text(encoding="utf-8")
    image_source = (ROOT / "forza" / "application" / "gui_read" / "image_reads.py").read_text(encoding="utf-8")

    assert "self._run_reads = GuiRunReadQueries(self._session_provider)" in service_source
    assert "return self._run_reads.list_runs(limit=limit)" in service_source
    assert "return self._run_reads.list_run_options(limit=limit)" in service_source
    assert "return self._run_reads.get_run(run_id)" in service_source

    moved_tokens = (
        "RunRepository(session)",
        "def _run_option(",
    )
    for token in moved_tokens:
        assert token not in service_source
        assert token in run_source

    assert "select(ExtractionRunEntity)" in run_source

    assert "from .run_reads import _run_option" in image_source
    assert "def _run_option(" not in image_source


def test_gui_run_reads_keep_public_service_facade_methods() -> None:
    source = (ROOT / "forza" / "application" / "gui_read_service.py").read_text(encoding="utf-8")

    assert "def list_runs(" in source
    assert "def list_run_options(" in source
    assert "def get_run(" in source


def test_gui_run_read_queries_public_contract() -> None:
    provider = GuiReadSessionProvider(Path("missing.sqlite"))
    queries = GuiRunReadQueries(provider)

    assert queries.list_runs() == []
    assert queries.list_run_options() == []
    assert queries.get_run("missing") is None


def test_run_option_label_uses_local_readable_time_and_processed_count() -> None:
    started_at = datetime(2026, 6, 15, 12, 34, 56, tzinfo=timezone.utc)
    row = SimpleNamespace(
        id="run-1",
        started_at=started_at,
        processed=3,
        succeeded=3,
        failed=0,
        mode="normal",
        status="completed",
    )

    option = _run_option(row)

    assert option.id == "run-1"
    assert option.label.startswith(started_at.astimezone().strftime("%Y-%m-%d %H:%M:%S"))
    assert "T" not in option.label
    assert "3 processed" in option.label
    assert option.label.endswith("normal · completed")
