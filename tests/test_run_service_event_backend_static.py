from __future__ import annotations

from pathlib import Path


RUN_SERVICE = Path("forza/application/run_service.py")


def _source() -> str:
    return RUN_SERVICE.read_text(encoding="utf-8")


def test_run_service_emits_typed_event_values() -> None:
    source = _source()

    assert "from ..events import EventSink, EventType, emit_event" in source
    assert 'emit_event(\n                self.event_sink,\n                "' not in source
    assert 'emit_event(self.event_sink, "' not in source


def test_run_service_uses_lmstudio_backend_constant() -> None:
    source = _source()

    assert "from ..lmstudio import LMSTUDIO_BACKEND_NAME, build_backend" in source
    legacy_backend_payload = '"backend": ' + '"lmstudio"'
    assert legacy_backend_payload not in source
    legacy_backend_label = "Backend: " + "lmstudio"
    assert legacy_backend_label not in source
