from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_ACTIVE_DOC_LINES = 550
MAX_ACTIVE_TEST_LINES = 650

# Plans and history are not current-contract documents: the documentation
# policy forbids citing them as behavior contracts, so they may exceed the
# active-document maintenance line limit.
NON_CURRENT_DOC_DIRS = {"history", "plans"}


def _active_markdown_docs() -> list[Path]:
    return [
        path
        for path in (ROOT / "docs").rglob("*.md")
        if not set(path.relative_to(ROOT / "docs").parts[:-1]) & NON_CURRENT_DOC_DIRS
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
    history = ROOT / "docs" / "history"
    if history.exists():
        assert not (history / "lab.md").exists()
        assert not (history / "lab_architecture.md").exists()
