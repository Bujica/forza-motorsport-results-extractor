"""Duplicate-group filter flow: identify -> filter -> select -> delete.

Regression coverage for the empty-list bug where the Images view sent the
combo *label* ("duplicate groups") instead of the *value* ("duplicate") and
the read query fail-closed to `where(False)`.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sqlmodel import Session

from forza.application import GuiReadService
from forza.application.gui_write_service import GuiWriteService
from forza.db import create_sqlite_engine
from forza.db.migrate import upgrade_database
from forza.db.models import ImageFileEntity
from forza.application.gui_read.image_reads import _duplicate_group_sort_key
from forza.gui.models.image_table_model import _group_sort_key

ROOT = Path(__file__).resolve().parents[1]


def _seed(path: Path) -> None:
    upgrade_database(path)
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            session.add(ImageFileEntity(
                id="img-c", file_hash="hash-1", current_name="c.png",
                current_path=str(path.parent / "c.png"),
                file_status="available",
            ))
            session.add(ImageFileEntity(
                id="img-d", file_hash="hash-1", current_name="d.png",
                current_path=str(path.parent / "d.png"),
                duplicate_of_image_file_id="img-c",
                file_status="available",
            ))
            session.add(ImageFileEntity(
                id="img-x", file_hash="hash-2", current_name="x.png",
                current_path=str(path.parent / "x.png"),
                file_status="available",
            ))
            session.commit()
    finally:
        engine.dispose()


def test_duplicate_filter_lists_group_members_and_canonical(tmp_path) -> None:
    db = tmp_path / "dup.sqlite3"
    _seed(db)
    reader = GuiReadService(db)
    try:
        got = {image.id for image in reader.list_images(inventory_filter="duplicate")}
    finally:
        reader.close()
    assert got == {"img-c", "img-d"}


def test_duplicate_filter_fail_closed_on_label_text(tmp_path) -> None:
    """The raw combo label must never match: unknown values return nothing.

    (The view now sends the combo *value* via `_combo_value`; this pins the
    fail-closed contract at the query layer.)
    """
    db = tmp_path / "dup.sqlite3"
    _seed(db)
    reader = GuiReadService(db)
    try:
        assert reader.list_images(inventory_filter="duplicate groups") == []
    finally:
        reader.close()


def test_duplicate_sort_key_groups_canonical_before_children() -> None:
    canon = SimpleNamespace(
        id="img-c", duplicate_of_image_file_id=None,
        file_hash="hash-1", current_name="c.png",
    )
    child = SimpleNamespace(
        id="img-d", duplicate_of_image_file_id="img-c",
        file_hash="hash-1", current_name="d.png",
    )
    other = SimpleNamespace(
        id="img-x", duplicate_of_image_file_id=None,
        file_hash="hash-2", current_name="x.png",
    )
    ordered = sorted([child, other, canon], key=_duplicate_group_sort_key)
    assert [image.id for image in ordered] == ["img-c", "img-d", "img-x"]


def test_view_sends_combo_value_for_inventory_filter() -> None:
    source = (ROOT / "forza" / "gui" / "views" / "image_browser_view.py").read_text(encoding="utf-8")
    assert "_combo_value(self.inventory_filter)" in source
    assert "self.inventory_filter.currentText()" not in source

def test_delete_duplicates_keeps_canonical_and_clears_group(tmp_path) -> None:
    db = tmp_path / "dup.sqlite3"
    _seed(db)
    writer = GuiWriteService(db)
    try:
        # Children have no evidence: fully removable.
        assert writer.delete_image_files(["img-d"]) == 1
    finally:
        writer.close()
    reader = GuiReadService(db)
    try:
        assert reader.list_images(inventory_filter="duplicate") == []
        remaining = {image.id for image in reader.list_images()}
    finally:
        reader.close()
    assert remaining == {"img-c", "img-x"}


def _row(id, name, dup_of=None):
    return SimpleNamespace(
        id=id,
        current_name=name,
        semantic_name=None,
        file_status="available",
        duplicate_of_image_file_id=dup_of,
        processing_status="unprocessed",
        best_lap_status="pending",
        race_date=None,
        race_datetime=None,
    )


def test_table_sort_keeps_groups_adjacent_under_name_sort() -> None:
    # Canonical "zebra" sorts last by name, but its child must follow it —
    # a plain name sort scattered them.
    zebra = _row("img-c", "zebra.png")
    child = _row("img-d", "apple.png", dup_of="img-c")
    solo = _row("img-x", "mango.png")
    by_id = {image.id: image for image in (zebra, child, solo)}
    ordered = sorted(
        [child, solo, zebra],
        key=lambda image: _group_sort_key(image, by_id, 0),
    )
    assert [image.id for image in ordered] == ["img-x", "img-c", "img-d"]
