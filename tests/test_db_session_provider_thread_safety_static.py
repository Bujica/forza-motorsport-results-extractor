from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "forza" / "application" / "db_session_provider.py"


def test_db_session_provider_engine_lifecycle_is_guarded_by_lock() -> None:
    source = SOURCE.read_text(encoding="utf-8")

    assert "import threading" in source
    assert "self._engine_lock = threading.Lock()" in source
    assert "def engine_for_db(self):" in source
    assert "def close(self) -> None:" in source

    engine_method = _method_source(source, "engine_for_db")
    close_method = _method_source(source, "close")

    assert "with self._engine_lock:" in engine_method
    assert engine_method.count("if self._engine is None:") >= 2
    assert "create_sqlite_engine(self.database_file)" in engine_method

    assert "with self._engine_lock:" in close_method
    assert "self._engine.dispose()" in close_method
    assert "self._engine = None" in close_method


def _method_source(source: str, method_name: str) -> str:
    marker = f"    def {method_name}"
    start = source.index(marker)
    next_match = source.find("\n    def ", start + len(marker))
    if next_match == -1:
        return source[start:]
    return source[start:next_match]
