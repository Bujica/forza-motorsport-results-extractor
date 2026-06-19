from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_CONTROLLER_FILES = (
    "forza/gui/controllers/process_controller.py",
    "forza/gui/controllers/image_debug_controller.py",
    "forza/gui/controllers/performance_controller.py",
    "forza/gui/controllers/review_controller.py",
    "forza/gui/controllers/image_controller.py",
    "forza/gui/controllers/best_laps_controller.py",
)

_STRING_EVENT_MATCH = re.compile(
    r"event\.type\s*(?:==|!=)\s*['\"]|event\.type\s+in\s*\{[^}]*['\"]",
    re.MULTILINE,
)


def test_controllers_use_event_type_members_for_pipeline_event_matching() -> None:
    for relative_path in _CONTROLLER_FILES:
        source = (ROOT / relative_path).read_text(encoding="utf-8-sig")
        assert "EventType" in source, relative_path
        assert not _STRING_EVENT_MATCH.search(source), relative_path
