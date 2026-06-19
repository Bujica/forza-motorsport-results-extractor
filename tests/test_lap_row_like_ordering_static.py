from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_lap_row_like_is_exported_by_domain_package() -> None:
    domain_init = (ROOT / "forza" / "domain" / "__init__.py").read_text(encoding="utf-8")
    ordering = (ROOT / "forza" / "domain" / "ordering.py").read_text(encoding="utf-8")

    assert "class LapRowLike(Protocol):" in ordering
    assert "from .ordering import" in domain_init
    assert "LapRowLike" in domain_init


def test_best_lap_ordering_adapters_use_structural_lap_contracts() -> None:
    controller = (ROOT / "forza" / "gui" / "controllers" / "best_laps_controller.py").read_text(encoding="utf-8")

    assert "Protocol" in controller
    assert "LapRowLike" in controller
    assert "best_lap_ms: int" in controller
    assert "def _row_from_lap(lap: _GuiBestLapSourceLike) -> BestLapRow:" in controller
    assert "def _row_from_external(record: _ExternalBestLapRecordLike) -> BestLapRow:" in controller
    assert "ordered_lap_key(row, {})" in controller
