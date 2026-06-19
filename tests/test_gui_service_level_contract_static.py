from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SERVICE_SOURCES = [
    ROOT / "forza" / "application" / "gui_read_service.py",
    ROOT / "forza" / "application" / "gui_read" / "session_provider.py",
    ROOT / "forza" / "application" / "gui_write_service.py",
]

SERVICE_TESTS = [
    ROOT / "tests" / "test_gui_read_and_rename.py",
    ROOT / "tests" / "test_gui_read_extended.py",
    ROOT / "tests" / "test_gui_write_image_status.py",
    ROOT / "tests" / "test_gui_write_flags_cases.py",
    ROOT / "tests" / "test_gui_write_dirty_decisions.py",
    ROOT / "tests" / "test_gui_write_field_decisions.py",
    ROOT / "tests" / "test_gui_write_standalone.py",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _forbidden_gui_runtime_tokens() -> tuple[str, ...]:
    qt_package = "Py" + "Side6"
    return (
        qt_package,
        "Q" + "Application",
        "Q" + "Widget",
        "Q" + "Dialog",
        "Q" + "Pixmap",
    )


def test_gui_read_write_services_are_qt_free_application_facades() -> None:
    for path in SERVICE_SOURCES:
        source = _read(path)
        for token in _forbidden_gui_runtime_tokens():
            assert token not in source, f"{path} must stay Qt-free; found {token}"

    assert "create_sqlite_engine" in _read(
        ROOT / "forza" / "application" / "gui_read" / "session_provider.py"
    )
    assert "create_sqlite_engine" in _read(ROOT / "forza" / "application" / "gui_write_service.py")


def test_gui_service_level_tests_do_not_require_qapplication_or_widgets() -> None:
    combined = "\n".join(_read(path) for path in SERVICE_TESTS)
    assert "GuiReadService" in combined
    assert "GuiWriteService" in combined

    for path in SERVICE_TESTS:
        source = _read(path)
        for token in _forbidden_gui_runtime_tokens():
            assert token not in source, f"{path} must stay service-level; found {token}"
