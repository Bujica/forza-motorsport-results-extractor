from __future__ import annotations

from pathlib import Path

from forza.application import gui_read_service
from forza.application.gui_read import types


ROOT = Path(__file__).resolve().parents[1]

def _token(*parts: str) -> str:
    return "".join(parts)


def test_gui_read_dto_types_move_out_of_service_surface() -> None:
    service_source = (ROOT / "forza" / "application" / "gui_read_service.py").read_text(encoding="utf-8")
    types_source = (ROOT / "forza" / "application" / "gui_read" / "types.py").read_text(encoding="utf-8")

    assert "from .gui_read.types import (" in service_source
    assert "from dataclasses import dataclass" not in service_source
    assert "@dataclass(frozen=True)" not in service_source

    dto_names = (
        "GuiImage",
        "GuiLap",
        "GuiExtractionResult",
        "GuiExtractionAttempt",
        "GuiImageDebugSummary",
        "GuiImageDebugDetail",
        "GuiImageDebugExtraction",
        "GuiImageDebugAttempt",
        "GuiImageDebugArtifact",
        "GuiImageDebugRuntime",
        "GuiImageDebugLap",
        "GuiImageDebugReview",
        "GuiReviewCase",
        "DashboardSummary",
        "GuiRunOption",
    )
    for name in dto_names:
        assert f"class {name}:" not in service_source
        assert f"class {name}:" in types_source

    assert _token("Gui", "Lab", "Sample", "Candidate") not in service_source
    assert _token("Gui", "Lab", "Sample", "Candidate") not in types_source


def test_gui_read_service_reexports_dto_types_for_existing_callers() -> None:
    assert gui_read_service.GuiImage is types.GuiImage
    assert gui_read_service.GuiLap is types.GuiLap
    assert gui_read_service.GuiExtractionResult is types.GuiExtractionResult
    assert gui_read_service.GuiExtractionAttempt is types.GuiExtractionAttempt
    assert gui_read_service.GuiImageDebugSummary is types.GuiImageDebugSummary
    assert gui_read_service.GuiImageDebugDetail is types.GuiImageDebugDetail
    assert gui_read_service.GuiReviewCase is types.GuiReviewCase
    assert not hasattr(gui_read_service, "GuiImageFlag")
    assert not hasattr(types, "GuiImageFlag")
    assert gui_read_service.DashboardSummary is types.DashboardSummary
    assert gui_read_service.GuiRunOption is types.GuiRunOption
