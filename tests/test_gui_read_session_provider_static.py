from __future__ import annotations

from pathlib import Path

from forza.application.gui_read.session_provider import GuiReadSessionProvider


ROOT = Path(__file__).resolve().parents[1]


def test_gui_read_session_provider_moves_engine_lifecycle_out_of_service() -> None:
    service_source = (ROOT / "forza" / "application" / "gui_read_service.py").read_text(encoding="utf-8")
    provider_source = (ROOT / "forza" / "application" / "gui_read" / "session_provider.py").read_text(encoding="utf-8")

    assert "GuiReadSessionProvider" in service_source
    assert "self._session_provider = GuiReadSessionProvider(database_file)" in service_source
    assert "return self._session_provider.can_read()" in service_source
    assert "return self._session_provider.session()" in service_source

    moved_tokens = (
        "create_sqlite_engine",
        "is_up_to_date",
        "self._engine = None",
        "self._schema_ready: bool | None = None",
        "def can_read(",
        "def get_engine(",
        "@contextmanager",
    )
    for token in moved_tokens:
        assert token not in service_source
        assert token in provider_source


def test_gui_read_service_keeps_session_compatibility_methods() -> None:
    source = (ROOT / "forza" / "application" / "gui_read_service.py").read_text(encoding="utf-8")

    assert "def close(self) -> None:" in source
    assert "def invalidate_schema_cache(self) -> None:" in source
    assert "def _can_read(self) -> bool:" in source
    assert "def _get_engine(self):" in source
    assert "def _session(self):" in source


def test_session_provider_public_contract() -> None:
    provider = GuiReadSessionProvider(Path("missing.sqlite"))

    assert provider.database_file == Path("missing.sqlite")
    assert provider.can_read() is False
    provider.invalidate_schema_cache()
    provider.close()
