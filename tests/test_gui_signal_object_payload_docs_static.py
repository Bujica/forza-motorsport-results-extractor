from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIGNAL_RE = re.compile(r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*Signal\((?P<args>[^)]*\bobject\b[^)]*)\)", re.MULTILINE)


def _object_signal_markers() -> list[str]:
    markers: list[str] = []
    for path in sorted((ROOT / "forza" / "gui").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8-sig")
        for match in SIGNAL_RE.finditer(text):
            markers.append(f"{relative}::{match.group('name')}")
    return markers


def test_all_gui_object_signals_are_documented() -> None:
    doc = (ROOT / "docs" / "contracts" / "gui_signal_payloads.md").read_text(encoding="utf-8")
    markers = _object_signal_markers()

    assert markers
    for marker in markers:
        assert f"`{marker}`" in doc
