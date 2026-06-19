"""Extended GuiReadService tests for non-lab read contracts."""
from __future__ import annotations

from pathlib import Path

from sqlmodel import Session

from forza.application import GuiReadService
from forza.db import create_sqlite_engine
from forza.db.migrate import upgrade_database
from forza.db.repositories import RunRepository, ImageFileRepository
from forza.db.repositories.model_results import ExtractionResultRepository
from forza.schemas import ExtractionResult, LapRecord, ModelExtractionAttempt, RaceSession


def _bootstrap(db_path: Path) -> None:
    upgrade_database(db_path)


def _add_image(session: Session, image_id: str, name: str) -> object:
    image = ImageFileRepository(session).upsert(
        image_id=image_id,
        file_hash=f"hash-{image_id}",
        file_name=name,
        current_name=name,
    )
    session.flush()
    return image


def _add_run(session: Session, run_id: str) -> object:
    run = RunRepository(session).create(run_id=run_id, backend="test", model="m")
    session.flush()
    return run


def _add_extraction_result(
    session: Session,
    *,
    run_id: str,
    image_id: str,
) -> object:
    result = ExtractionResult(
        source_file=f"{image_id}.png",
        file_hash=f"hash-{run_id}-{image_id}",
        session=RaceSession(
            track="Lime Rock Park Full Circuit",
            temp_f=76.0,
            temp_c=24.4,
            entries=[LapRecord("Bujica89", "Car", "D", "01:00.000", 60000)],
            race_class="D",
            weather="dry",
        ),
        status="ok",
        model_attempts=[
            ModelExtractionAttempt(attempt_number=1, status="ok", accepted=True)
        ],
    )
    return ExtractionResultRepository(session).add_result(
        result,
        run_id=run_id,
        image_file_id=image_id,
    )


def test_get_extraction_result_returns_most_recent_run(tmp_path: Path) -> None:
    """When the same image was processed in two runs, the latest result is returned."""
    db_path = tmp_path / "forza.sqlite3"
    _bootstrap(db_path)

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            _add_run(session, "run-old")
            _add_run(session, "run-new")
            _add_image(session, "img-1", "image.png")
            _add_extraction_result(session, run_id="run-old", image_id="img-1")
            session.commit()
            _add_extraction_result(session, run_id="run-new", image_id="img-1")
            session.commit()
    finally:
        engine.dispose()

    gui = GuiReadService(db_path)
    result = gui.get_extraction_result("img-1")
    gui.close()

    assert result is not None
    assert result.run_id == "run-new"


def test_get_extraction_result_with_run_id_filter_returns_specific_run(tmp_path: Path) -> None:
    """Passing run_id must return the result from that specific run."""
    db_path = tmp_path / "forza.sqlite3"
    _bootstrap(db_path)

    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            _add_run(session, "run-old")
            _add_run(session, "run-new")
            _add_image(session, "img-1", "image.png")
            _add_extraction_result(session, run_id="run-old", image_id="img-1")
            _add_extraction_result(session, run_id="run-new", image_id="img-1")
            session.commit()
    finally:
        engine.dispose()

    gui = GuiReadService(db_path)
    result = gui.get_extraction_result("img-1", run_id="run-old")
    gui.close()

    assert result is not None
    assert result.run_id == "run-old"
