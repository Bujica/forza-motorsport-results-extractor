from __future__ import annotations

from pathlib import Path


EXTRACTION_SERVICE = Path("forza/application/extraction_service.py")


def _source() -> str:
    return EXTRACTION_SERVICE.read_text(encoding="utf-8")


def test_extraction_service_emits_typed_event_values() -> None:
    source = _source()

    assert "from ..events import EventSink, EventType, emit_event" in source
    assert "EventType.BATCH_STARTED" in source
    assert "EventType.BATCH_FINISHED" in source
    assert "EventType.IMAGE_STARTED" in source
    assert "EventType.IMAGE_FINISHED" in source
    assert "EventType.PERSISTENCE_FAILED" in source

    legacy_events = [
        "batch" + "_started",
        "batch" + "_finished",
        "image" + "_started",
        "image" + "_finished",
        "persistence" + "_failed",
    ]
    for event_name in legacy_events:
        assert f'emit_event(self.event_sink, "{event_name}"' not in source
        assert f'"{event_name}",' not in source
