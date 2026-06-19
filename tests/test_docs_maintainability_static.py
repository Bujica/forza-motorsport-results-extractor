from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_ACTIVE_DOC_LINES = 550
MAX_ACTIVE_TEST_LINES = 650


def _active_markdown_docs() -> list[Path]:
    return [
        path
        for path in (ROOT / "docs").rglob("*.md")
        if "history" not in path.relative_to(ROOT / "docs").parts
    ]


def test_active_docs_stay_below_maintenance_line_limit() -> None:
    oversized = []
    for path in _active_markdown_docs():
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > MAX_ACTIVE_DOC_LINES:
            oversized.append((path.relative_to(ROOT).as_posix(), line_count))

    assert oversized == []


def test_active_tests_stay_below_maintenance_line_limit() -> None:
    oversized = []
    for path in sorted((ROOT / "tests").glob("*.py")):
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > MAX_ACTIVE_TEST_LINES:
            oversized.append((path.relative_to(ROOT).as_posix(), line_count))

    assert oversized == []


def test_removed_lab_architecture_is_not_active() -> None:
    assert not (ROOT / "docs" / "architecture" / "lab.md").exists()
    assert not (ROOT / "docs" / "history").exists()
