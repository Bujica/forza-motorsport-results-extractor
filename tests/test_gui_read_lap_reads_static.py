from __future__ import annotations

from pathlib import Path

from forza.application.gui_read.lap_reads import GuiLapReadQueries
from forza.application.gui_read.session_provider import GuiReadSessionProvider


ROOT = Path(__file__).resolve().parents[1]


def test_gui_lap_reads_move_lap_methods_out_of_service() -> None:
    service_source = (ROOT / "forza" / "application" / "gui_read_service.py").read_text(encoding="utf-8")
    lap_source = (ROOT / "forza" / "application" / "gui_read" / "lap_reads.py").read_text(encoding="utf-8")

    assert "self._lap_reads = GuiLapReadQueries(self._session_provider)" in service_source
    assert "return self._lap_reads.list_laps(" in service_source

    moved_tokens = (
        "LapRecordEntity.image_file_id == image_file_id",
        "LapRecordEntity.best_lap_ms",
        "def _lap(",
    )
    for token in moved_tokens:
        assert token not in service_source
        assert token in lap_source

    assert "select(LapRecordEntity, ImageFileEntity).join(" in lap_source
    assert "select(ImageFileEntity).where(ImageFileEntity.id.in_(image_ids))" not in lap_source


def test_gui_lap_reads_keep_public_service_facade_method() -> None:
    source = (ROOT / "forza" / "application" / "gui_read_service.py").read_text(encoding="utf-8")

    assert "def list_laps(" in source
    assert "image_file_id: str | None = None" in source
    assert "best_only: bool | None = None" in source


def test_gui_lap_reads_use_best_lap_order_index_shape() -> None:
    source = (ROOT / "forza" / "application" / "gui_read" / "lap_reads.py").read_text(encoding="utf-8")

    assert "elif best_only is True:" in source
    assert "LapRecordEntity.weather" in source
    assert "LapRecordEntity.driver" in source
    assert "LapRecordEntity.car" in source


def test_gui_lap_read_queries_public_contract() -> None:
    provider = GuiReadSessionProvider(Path("missing.sqlite"))
    queries = GuiLapReadQueries(provider)

    assert queries.list_laps() == []
