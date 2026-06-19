from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, select

from forza.application import image_service as image_inventory_service
from forza.application.database_service import DatabaseService
from forza.application.image_service import ImageInventoryResult, ImageInventoryService
from forza.db import create_sqlite_engine
from forza.db.migrate import upgrade_database
from forza.db.models import ImageFileEntity, ImageFlagEntity
from forza.db.repositories import ImageFileRepository
from forza.pipeline.image import DiscoveredImage, DuplicateImage, ExistingImage, ImageDiscoveryPlan


class _FakeDatabaseService:
    def __init__(self) -> None:
        self.inventory_calls = 0
        self.register_calls = []

    def image_inventory(self):
        self.inventory_calls += 1
        return {"known-hash"}, {"known-path"}

    def register_image_file(self, **kwargs) -> None:
        self.register_calls.append(kwargs)


def _plan() -> ImageDiscoveryPlan:
    return ImageDiscoveryPlan(
        total=4,
        new_images=[
            DiscoveredImage(Path("new-1.png"), "new-hash-1"),
            DiscoveredImage(Path("new-2.png"), "new-hash-2"),
        ],
        duplicates=[
            DuplicateImage(
                path=Path("dup.png"),
                file_hash="dup-hash",
                reason="cached",
                duplicate_of_hash="original-hash",
            )
        ],
        existing_images=[ExistingImage(Path("existing.png"), "existing-hash")],
    )


def test_classify_builds_inventory_result_from_discovery_plan(monkeypatch) -> None:
    database = _FakeDatabaseService()
    plan_calls = []
    plan = _plan()

    def fake_plan_images(images, known_hashes, *, known_paths, force):
        plan_calls.append((images, known_hashes, known_paths, force))
        return plan

    monkeypatch.setattr(image_inventory_service, "plan_images", fake_plan_images)
    service = ImageInventoryService(database)
    images = [Path("a.png"), Path("b.png")]

    result = service.classify(images, force=True)

    assert database.inventory_calls == 1
    assert plan_calls == [(images, {"known-hash"}, {"known-path"}, True)]
    assert result == ImageInventoryResult(
        plan=plan,
        new_count=2,
        existing_count=1,
        duplicate_count=1,
    )


def test_register_persists_new_and_duplicate_images(monkeypatch) -> None:
    database = _FakeDatabaseService()
    skipped_calls = []
    plan = _plan()

    def fake_log_duplicate_skips(plan_arg):
        skipped_calls.append(plan_arg)
        return [Path("dup.png")]

    monkeypatch.setattr(image_inventory_service, "log_duplicate_skips", fake_log_duplicate_skips)
    service = ImageInventoryService(database)
    result = ImageInventoryResult(
        plan=plan,
        new_count=2,
        existing_count=1,
        duplicate_count=1,
    )

    service.register(result, run_id="run-1")

    assert skipped_calls == [plan]
    assert database.register_calls == [
        {"file_hash": "new-hash-1", "path": Path("new-1.png")},
        {"file_hash": "new-hash-2", "path": Path("new-2.png")},
        {
            "file_hash": "dup-hash",
            "path": Path("dup.png"),
            "duplicate_of_hash": "original-hash",
            "run_id": "run-1",
        },
    ]


def test_register_does_not_log_duplicate_summary_when_no_duplicates_skipped(monkeypatch, caplog) -> None:
    database = _FakeDatabaseService()
    plan = ImageDiscoveryPlan(
        total=1,
        new_images=[DiscoveredImage(Path("new.png"), "new-hash")],
        duplicates=[],
        existing_images=[],
    )
    monkeypatch.setattr(image_inventory_service, "log_duplicate_skips", lambda plan_arg: [])
    service = ImageInventoryService(database)

    service.register(ImageInventoryResult(plan=plan, new_count=1, existing_count=0, duplicate_count=0))

    assert database.register_calls == [{"file_hash": "new-hash", "path": Path("new.png")}]
    assert "Registered" not in caplog.text


def test_scan_input_folder_registers_unprocessed_images_and_marks_missing(tmp_path) -> None:
    db_path = tmp_path / "forza.sqlite3"
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    fresh = input_dir / "fresh.png"
    stale = input_dir / "stale.png"
    fresh.write_text("fresh", encoding="utf-8")
    stale.write_text("stale", encoding="utf-8")
    upgrade_database(db_path)

    database = DatabaseService(db_path)
    try:
        first = ImageInventoryService(database).scan_input_folder(input_dir)
        stale.unlink()
        second = ImageInventoryService(database).scan_input_folder(input_dir)
    finally:
        database.close()

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            rows = session.exec(select(ImageFileEntity)).all()
    finally:
        engine.dispose()

    by_name = {row.current_name: row for row in rows}
    assert first.total_files == 2
    assert first.registered == 2
    assert second.total_files == 1
    assert second.refreshed == 1
    assert second.missing == 1
    assert by_name["fresh.png"].file_status == "available"
    assert by_name["stale.png"].file_status == "missing"


def test_scan_input_folder_marks_duplicate_files_before_processing(tmp_path) -> None:
    db_path = tmp_path / "forza.sqlite3"
    input_dir = tmp_path / "input"
    nested_dir = input_dir / "nested"
    nested_dir.mkdir(parents=True)
    original = input_dir / "same.png"
    duplicate_same_name = nested_dir / "same.png"
    duplicate_other_name = input_dir / "copy.png"
    for path in (original, duplicate_same_name, duplicate_other_name):
        path.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
            b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x01\x01"
            b"\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
        )
    upgrade_database(db_path)

    database = DatabaseService(db_path)
    try:
        ImageInventoryService(database).scan_input_folder(input_dir)
    finally:
        database.close()

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            rows = session.exec(select(ImageFileEntity)).all()
            flags = session.exec(select(ImageFlagEntity)).all()
    finally:
        engine.dispose()

    canonical = next(row for row in rows if row.duplicate_of_image_file_id is None)
    duplicates = [row for row in rows if row.duplicate_of_image_file_id == canonical.id]
    duplicate_paths = {Path(row.current_path) for row in duplicates}
    expected_duplicate_paths = {original, duplicate_same_name, duplicate_other_name} - {Path(canonical.current_path)}
    assert len(rows) == 3
    assert len(duplicates) == 2
    assert duplicate_paths == expected_duplicate_paths
    assert [flag.flag_type for flag in flags] == ["duplicate", "duplicate"]


def test_scan_input_folder_does_not_anchor_available_duplicate_to_missing_source(tmp_path) -> None:
    db_path = tmp_path / "forza.sqlite3"
    input_dir = tmp_path / "input"
    nested_dir = input_dir / "New folder"
    nested_dir.mkdir(parents=True)
    nested = nested_dir / "Brands Hatch Grand Prix Circuit - A.png"
    restored = input_dir / "Brands Hatch Grand Prix Circuit - A.png"
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x01\x01"
        b"\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    nested.write_bytes(png_bytes)
    upgrade_database(db_path)

    database = DatabaseService(db_path)
    try:
        service = ImageInventoryService(database)
        service.scan_input_folder(input_dir)
        nested.unlink()
        service.scan_input_folder(input_dir)
        restored.write_bytes(png_bytes)
        service.scan_input_folder(input_dir)
    finally:
        database.close()

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            rows = session.exec(select(ImageFileEntity)).all()
            active_duplicate_flags = session.exec(
                select(ImageFlagEntity).where(
                    ImageFlagEntity.flag_type == "duplicate",
                    ImageFlagEntity.status == "active",
                )
            ).all()
    finally:
        engine.dispose()

    by_path = {Path(row.current_path): row for row in rows}
    assert by_path[nested].file_status == "missing"
    assert by_path[nested].duplicate_of_image_file_id is None
    assert by_path[restored].file_status == "available"
    assert by_path[restored].duplicate_of_image_file_id is None
    assert active_duplicate_flags == []


def test_selected_image_files_keeps_selection_order_and_ignores_unavailable(tmp_path) -> None:
    db_path = tmp_path / "forza.sqlite3"
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    available = input_dir / "available.png"
    other = input_dir / "other.png"
    missing = input_dir / "missing.png"
    available.write_text("available", encoding="utf-8")
    other.write_text("other", encoding="utf-8")
    upgrade_database(db_path)

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            repo = ImageFileRepository(session)
            repo.upsert(
                image_id="available",
                file_hash="hash-available",
                file_name=available.name,
                current_name=available.name,
                current_path=available,
            )
            repo.upsert(
                image_id="other",
                file_hash="hash-other",
                file_name=other.name,
                current_name=other.name,
                current_path=other,
            )
            row = repo.upsert(
                image_id="missing",
                file_hash="hash-missing",
                file_name=missing.name,
                current_name=missing.name,
                current_path=missing,
            )
            row.file_status = "missing"
            session.add(row)
            session.commit()
    finally:
        engine.dispose()

    database = DatabaseService(db_path)
    try:
        selected = database.selected_image_files(["other", "missing", "available", "other"])
    finally:
        database.close()

    assert selected == [(other, "hash-other"), (available, "hash-available")]

