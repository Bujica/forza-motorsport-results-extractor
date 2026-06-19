from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "forza" / "application" / "run_lifecycle_service.py"


def test_reconcile_abandoned_runs_isolates_each_run() -> None:
    source = SOURCE_PATH.read_text(encoding="utf-8")

    assert "import logging" in source
    assert '_log = logging.getLogger("forza")' in source
    assert "recovered = 0" in source
    assert "for run_id in run_ids:" in source
    assert "try:" in source
    assert "except Exception:" in source
    assert "Could not reconcile abandoned run %s" in source
    assert "exc_info=True" in source
    assert "recovered += 1" in source
    assert "return recovered" in source
    assert "return len(run_ids)" not in source
