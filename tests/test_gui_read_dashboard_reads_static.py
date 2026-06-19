from __future__ import annotations

from pathlib import Path

from forza.application.gui_read.dashboard_reads import GuiDashboardReadQueries
from forza.application.gui_read.session_provider import GuiReadSessionProvider


ROOT = Path(__file__).resolve().parents[1]

def _token(*parts: str) -> str:
    return "".join(parts)


def test_gui_dashboard_reads_move_dashboard_logic_out_of_service() -> None:
    service_source = (ROOT / "forza" / "application" / "gui_read_service.py").read_text(encoding="utf-8")
    dashboard_source = (ROOT / "forza" / "application" / "gui_read" / "dashboard_reads.py").read_text(encoding="utf-8")

    assert "self._dashboard_reads = GuiDashboardReadQueries(self._session_provider)" in service_source
    assert "return self._dashboard_reads.dashboard_summary()" in service_source
    assert "list_lab_sample" not in service_source
    assert "list_lab_sample" not in dashboard_source
    assert _token("Gui", "Lab", "Sample", "Candidate") not in dashboard_source
    assert "LAB_SELECTION_FLAGS" not in dashboard_source


def test_gui_dashboard_reads_keep_public_service_facade_methods() -> None:
    source = (ROOT / "forza" / "application" / "gui_read_service.py").read_text(encoding="utf-8")

    assert "def dashboard_summary(" in source
    assert "def list_lab_sample_candidates(" not in source
    assert "def list_lab_sample_flag_candidates(" not in source


def test_gui_dashboard_read_queries_public_contract() -> None:
    provider = GuiReadSessionProvider(Path("missing.sqlite"))
    queries = GuiDashboardReadQueries(provider)

    assert queries.dashboard_summary().images == 0
