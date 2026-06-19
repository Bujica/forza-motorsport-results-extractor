from __future__ import annotations

import json
from pathlib import Path

from forza.config import load_config
from forza.db.repositories import ExtractionResultRepository, ReviewRepository
from forza.db.session import create_sqlite_engine
from forza.db.testing import create_test_db_and_tables
from forza.schemas import ExtractionResult, ModelExtractionAttempt, ReviewCase
from sqlmodel import Session


def test_extraction_result_repository_persists_raw_response(tmp_path: Path) -> None:
    db_path = tmp_path / "forza.sqlite3"
    engine = create_sqlite_engine(db_path)
    create_test_db_and_tables(engine)

    with Session(engine) as session:
        # Direct entity insertion avoids needing the full service stack here.
        from forza.db.models import ExtractionAttemptEntity, ExtractionRunEntity, RunInputEntity, ImageFileEntity
        session.add(ExtractionRunEntity(id="run", backend="test", model="model", status="completed"))
        session.add(ImageFileEntity(
            id="img",
            file_hash="hash",
            file_name="shot.png",
            current_name="shot.png",
            current_path=str(tmp_path / "shot.png"),
        ))
        session.flush()
        run_input = RunInputEntity(
            run_id="run",
            image_file_id="img",
            input_order=0,
            input_path="shot.png",
            decision="process",
        )
        session.add(run_input)
        session.flush()
        result = ExtractionResult(
            "shot.png",
            "hash",
            None,
            "ok",
            raw_response='{"t":"Track","e":[]}',
            raw_response_payload={"t": "Track", "e": []},
            raw_response_artifact_path=str(tmp_path / "raw.json"),
            model_attempts=[
                ModelExtractionAttempt(
                    attempt_number=1,
                    status="ok",
                    accepted=True,
                    raw_response='{"t":"Track","e":[]}',
                )
            ],
        )

        entity = ExtractionResultRepository(session).add_result(
            result,
            run_id="run",
            image_file_id="img",
        )
        session.commit()
        session.refresh(entity)

        attempt = session.get(ExtractionAttemptEntity, entity.accepted_attempt_id)
        assert attempt.raw_response == '{"t":"Track","e":[]}'
        assert attempt.parsed_json is None


def test_review_repository_persists_gui_linkage_fields(tmp_path: Path) -> None:
    db_path = tmp_path / "forza.sqlite3"
    engine = create_sqlite_engine(db_path)
    create_test_db_and_tables(engine)

    with Session(engine) as session:
        from forza.db.models import ExtractionResultEntity, ExtractionRunEntity, RunInputEntity, ImageFileEntity
        session.add(ExtractionRunEntity(id="run", backend="test", model="model", status="completed"))
        session.add(ImageFileEntity(
            id="img",
            file_hash="hash",
            file_name="shot.png",
            current_name="shot.png",
            current_path=str(tmp_path / "shot.png"),
        ))
        session.flush()
        run_input = RunInputEntity(
            run_id="run",
            image_file_id="img",
            input_order=0,
            input_path="shot.png",
            decision="process",
        )
        session.add(run_input)
        session.flush()
        session.add(ExtractionResultEntity(
            id="result",
            run_id="run",
            run_input_id=run_input.id,
            image_file_id="img",
            status="ok",
        ))
        case = ReviewCase(
            reason="dirty_lap",
            source_file="shot.png",
            track="Track",
            race_class="D",
            weather="dry",
            temp_f=70.0,
            driver="Bujica89",
            car="Car",
            best_lap="00:56.000",
            image_file_id="img",
            run_id="run",
            extraction_result_id="result",
        )

        entity = ReviewRepository(session).add_case(case)
        session.commit()
        session.refresh(entity)

        assert entity.image_file_id == "img"
        assert entity.run_id == "run"
        assert entity.extraction_result_id == "result"
