from __future__ import annotations

import ast
from pathlib import Path
from typing import get_type_hints

from forza.application.gui_write_service import GuiWriteService
from forza.events import EventType


def test_gui_write_service_emit_requires_event_type() -> None:
    annotations = get_type_hints(GuiWriteService._emit)
    assert annotations["event_type"] is EventType


def test_gui_write_service_does_not_emit_string_literals() -> None:
    source_path = Path("forza/application/gui_write_service.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if not (
            isinstance(function, ast.Attribute)
            and function.attr == "_emit"
            and isinstance(function.value, ast.Name)
            and function.value.id == "self"
        ):
            continue
        if not node.args:
            continue
        event_arg = node.args[0]
        if isinstance(event_arg, ast.Constant) and isinstance(event_arg.value, str):
            violations.append((node.lineno, event_arg.value))
    assert violations == []
