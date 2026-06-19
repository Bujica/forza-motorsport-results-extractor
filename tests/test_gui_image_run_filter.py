from __future__ import annotations

from sqlmodel import Session

from forza.application import GuiReadService
from forza.db import create_sqlite_engine
from forza.db.migrate import upgrade_database
from forza.db.models import RunInputEntity
from forza.db.repositories import ImageFlagRepository, ImageFileRepository, RunRepository


def _seed_duplicate_run_input_only_fixture(db_path) -> None:
    upgrade_database(db_path)
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            RunRepository(session).create(run_id="run-c", backend="lmstudio", model="test-model", prompt_name="p1")
            repo = ImageFileRepository(session)
            canonical = repo.upsert(
                image_id="img-c-canonical",
                file_hash="hash-img-c-duplicate-group",
                file_name="img-c-canonical.png",
                current_name="img-c-canonical.png",
                current_path="img-c-canonical.png",
            )
            duplicate = repo.upsert(
                image_id="img-c-duplicate",
                file_hash="hash-img-c-duplicate-group",
                file_name="img-c-duplicate.png",
                current_name="img-c-duplicate.png",
                current_path="img-c-duplicate.png",
                duplicate_of_image_file_id=canonical.id,
            )
            ImageFlagRepository(session).add_flag(image_file_id=duplicate.id, run_id="run-c", flag="duplicate")
            session.add(
                RunInputEntity(
                    run_id="run-c",
                    image_file_id=duplicate.id,
                    input_order=0,
                    input_path="img-c-duplicate.png",
                    file_name="img-c-duplicate.png",
                    file_hash=duplicate.file_hash,
                    decision="skip",
                    skip_reason="dry_run",
                )
            )
            session.commit()
    finally:
        engine.dispose()


def test_image_run_filter_uses_run_inputs_not_laps(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    _seed_duplicate_run_input_only_fixture(db_path)

    gui = GuiReadService(db_path)

    assert [image.id for image in gui.list_images(run_id="run-c")] == ["img-c-duplicate"]

    duplicate_group_ids = [image.id for image in gui.list_images(inventory_filter="duplicate")]
    assert duplicate_group_ids == ["img-c-canonical", "img-c-duplicate"]

    duplicate_group_ids_for_run = [image.id for image in gui.list_images(run_id="run-c", inventory_filter="duplicate")]
    assert duplicate_group_ids_for_run == ["img-c-canonical", "img-c-duplicate"]

    _tracks, runs = gui.image_filter_values(inventory_filter="duplicate")
    assert [run.id for run in runs] == ["run-c"]

    assert gui.list_images(inventory_filter="track") == []
