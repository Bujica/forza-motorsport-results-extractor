# Shared fixtures and helpers for split GUI write tests.

from pathlib import Path

import pytest

from sqlmodel import Session, select

from forza.db import create_sqlite_engine

from forza.db.migrate import upgrade_database

from forza.db.repositories import ImageFlagRepository, RunRepository, ImageFileRepository

from forza.db.models import ImageFlagEntity, LapRecordEntity, ReviewCaseEntity, ReviewCorrectionEntity, ImageFileEntity

from forza.events import PipelineEvent

from forza.gui import GuiReadService

from forza.application import GuiWriteService, ReviewDecisionTargetNotFound

from tests.db_test_helpers import add_extraction_result_parent

def _seed(db_path: Path, image_path: Path) -> tuple[str, str, str, str]:
    upgrade_database(db_path)
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            RunRepository(session).create(run_id="run-1", backend="test", model="model")
            image = ImageFileRepository(session).upsert(
                image_id="img-1",
                file_hash="hash-1",
                file_name=image_path.name,
                current_name=image_path.name,
                current_path=image_path,
                semantic_name="Mugello Circuit Full Circuit - TCR #1.png",
            )
            add_extraction_result_parent(
                session,
                run_id="run-1",
                image_file_id=image.id,
                result_id="result-1",
                file_name=image_path.name,
                file_hash=image.file_hash,
            )
            flag = ImageFlagRepository(session).add_flag(
                image_file_id=image.id,
                run_id="run-1",
                flag="duplicate",
                reason="test flag",
            )
            lap = LapRecordEntity(
                id="lap-1",
                extraction_result_id="result-1",
                run_id="run-1",
                image_file_id=image.id,
                source_file=image.current_name,
                lap_index=0,
                track="Mugello Circuit Full Circuit",
                race_class="TCR",
                weather="dry",
                driver="Bujica89",
                car="Honda Civic",
                best_lap="01:00.000",
                best_lap_ms=60000,
                dirty=True,
                is_best_lap=True,
            )
            session.add(lap)
            case = ReviewCaseEntity(
                id="case-1",
                case_number=1,
                image_file_id=image.id,
                run_id="run-1",
                extraction_result_id="result-1",
                lap_record_id=lap.id,
                source_file=image.current_name,
                reason="track",
                trigger="track_unknown",
                track="Mugello Circuit Full Circuit",
                race_class="TCR",
                weather="dry",
            )
            session.add(case)
            session.commit()
            return image.id, flag.id, case.id, lap.id
    finally:
        engine.dispose()

def _add_lap_for_image(
    session: Session,
    *,
    image_id: str,
    image_name: str,
    result_id: str,
    lap_id: str,
    lap_index: int,
    best_lap: str,
    best_lap_ms: int,
    driver: str = "Driver2",
) -> None:
    add_extraction_result_parent(
        session,
        run_id="run-1",
        image_file_id=image_id,
        result_id=result_id,
        file_name=image_name,
    )
    session.add(
        LapRecordEntity(
            id=lap_id,
            extraction_result_id=result_id,
            run_id="run-1",
            image_file_id=image_id,
            source_file=image_name,
            lap_index=lap_index,
            track="Mugello Circuit Full Circuit",
            race_class="TCR",
            weather="dry",
            driver=driver,
            car="Honda Civic",
            best_lap=best_lap,
            best_lap_ms=best_lap_ms,
            dirty=False,
            is_best_lap=True,
        )
    )

__all__ = [name for name in globals() if not name.startswith("__")]
