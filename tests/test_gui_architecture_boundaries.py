from __future__ import annotations

from pathlib import Path


GUI_ROOT = Path(__file__).resolve().parents[1] / "forza" / "gui"


def _python_files(path: Path) -> list[Path]:
    return sorted(path.rglob("*.py"))


def test_views_do_not_import_repositories_or_sqlmodel() -> None:
    view_dir = GUI_ROOT / "views"
    forbidden = ("forza.db.repositories", "..db.repositories", "sqlmodel", "Session")

    for path in _python_files(view_dir):
        source = path.read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden), path


def test_controllers_do_not_import_sqlmodel_session() -> None:
    controller_dir = GUI_ROOT / "controllers"
    forbidden = ("from sqlmodel import Session", "sqlmodel.Session", "from sqlalchemy.orm import Session")

    for path in _python_files(controller_dir):
        source = path.read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden), path


def test_event_bridge_sink_does_not_touch_widgets() -> None:
    source = (GUI_ROOT / "workers" / "event_bridge.py").read_text(encoding="utf-8")

    assert ".emit(event)" in source
    assert "QWidget" not in source
    assert "setText" not in source
    assert "setPixmap" not in source

def test_gui_package_does_not_import_database_or_sqlmodel_directly() -> None:
    forbidden = (
        "from sqlmodel import",
        "import sqlmodel",
        "from sqlalchemy import",
        "import sqlalchemy",
        "from ..db",
        "from ...db",
        "forza.db",
    )

    for path in _python_files(GUI_ROOT):
        source = path.read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden), path


def test_gui_read_services_live_in_application_layer() -> None:
    assert not (GUI_ROOT / "read_service.py").exists()
    assert not (GUI_ROOT / "read_service_best_laps.py").exists()
    assert not (GUI_ROOT / "database_state.py").exists()
    assert (GUI_ROOT.parent / "application" / "gui_read_service.py").exists()
    assert (GUI_ROOT.parent / "application" / "gui_read_service_best_laps.py").exists()
    assert (GUI_ROOT.parent / "application" / "gui_database_state.py").exists()
    assert (GUI_ROOT.parent / "application" / "gui_overview_service.py").exists()


def test_non_gui_code_does_not_import_deleted_gui_read_service() -> None:
    for path in sorted((GUI_ROOT.parent).rglob("*.py")):
        if ".git" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        assert "forza.gui.read_service" not in source, path
        assert "..gui.read_service" not in source, path
        assert ".gui.read_service" not in source, path

