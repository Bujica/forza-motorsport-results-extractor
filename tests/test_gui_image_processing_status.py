from pathlib import Path

from sqlmodel import Session

from forza.application import GuiReadService
from forza.db import create_sqlite_engine
from forza.db.migrate import upgrade_database
from forza.db.models import RunInputEntity
from forza.db.repositories import ImageFileRepository, RunRepository
from forza.db.repositories.model_results import ExtractionResultRepository
from forza.schemas import ExtractionResult, LapRecord, ModelExtractionAttempt, RaceSession


def _ok_result(source_file: str, file_hash: str) -> ExtractionResult:
    return ExtractionResult(
        source_file=source_file,
        file_hash=file_hash,
        image_file_id="img-ok",
        session=RaceSession(
            track="Mugello Circuit Full Circuit",
            temp_f=77.0,
            temp_c=25.0,
            entries=[LapRecord("Bujica89", "Honda Civic", "TCR", "01:58.123", 118123, False)],
            race_class="TCR",
            weather="dry",
        ),
        status="ok",
        model_attempts=[
            ModelExtractionAttempt(
                attempt_number=1,
                status="ok",
                accepted=True,
                raw_response='{"ok":true}',
            )
        ],
    )


def test_gui_read_service_derives_image_processing_status_from_latest_result(tmp_path: Path) -> None:
    db_path = tmp_path / "forza.sqlite3"
    upgrade_database(db_path)
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            runs = RunRepository(session)
            images = ImageFileRepository(session)
            results = ExtractionResultRepository(session)
            runs.create(run_id="run-ok", backend="lmstudio", model="test-model", prompt_name="p1")
            runs.create(run_id="run-error", backend="lmstudio", model="test-model", prompt_name="p1")

            for image_id, file_hash in (
                ("img-ok", "hash-ok"),
                ("img-error", "hash-error"),
                ("img-new", "hash-new"),
                ("img-duplicate", "hash-duplicate"),
                ("img-dry-run", "hash-dry-run"),
            ):
                images.upsert(
                    image_id=image_id,
                    file_hash=file_hash,
                    file_name=f"{image_id}.png",
                    current_name=f"{image_id}.png",
                    current_path=tmp_path / f"{image_id}.png",
                )

            results.add_result(_ok_result("img-ok.png", "hash-ok"), run_id="run-ok", image_file_id="img-ok")
            results.add_result(
                ExtractionResult(
                    source_file="img-error.png",
                    file_hash="hash-error",
                    image_file_id="img-error",
                    session=None,
                    status="error",
                    error="failed",
                    model_attempts=[
                        ModelExtractionAttempt(
                            attempt_number=1,
                            status="error",
                            accepted=False,
                            rejected_reason="transport_error",
                        )
                    ],
                ),
                run_id="run-error",
                image_file_id="img-error",
            )
            session.add(
                RunInputEntity(
                    run_id="run-ok",
                    image_file_id="img-duplicate",
                    input_order=1,
                    input_path="img-duplicate.png",
                    file_name="img-duplicate.png",
                    file_hash="hash-duplicate",
                    decision="duplicate",
                    skip_reason="duplicate",
                )
            )
            session.add(
                RunInputEntity(
                    run_id="run-ok",
                    image_file_id="img-dry-run",
                    input_order=2,
                    input_path="img-dry-run.png",
                    file_name="img-dry-run.png",
                    file_hash="hash-dry-run",
                    decision="process",
                    process_reason="dry_run",
                )
            )
            session.commit()
    finally:
        engine.dispose()

    gui = GuiReadService(db_path)

    statuses = {image.id: str(image.processing_status) for image in gui.list_images()}
    assert statuses == {
        "img-ok": "processed_ok",
        "img-error": "processed_error",
        "img-new": "unprocessed",
        "img-duplicate": "skipped",
        "img-dry-run": "unprocessed",
    }
    assert [image.id for image in gui.list_images(processing_status="unprocessed")] == ["img-dry-run", "img-new"]
    assert [image.id for image in gui.list_images(processing_status="skipped")] == ["img-duplicate"]
    assert [image.id for image in gui.list_images(processing_status="processed_error")] == ["img-error"]
