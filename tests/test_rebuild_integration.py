"""Integration tests for RebuildService.rebuild_outputs().

Verifies end-to-end derived-state rebuild behaviour: DB seeded -> rebuild called
-> review cases returned. PDF/export and external-record import are explicit Best
Laps actions, not rebuild side effects.
"""
from __future__ import annotations

import dataclasses
import logging
from pathlib import Path

from forza.config import load_config
from forza.domain.normalizer import ReferenceData, load_reference_seed_text_data
from forza.schemas import ExtractionResult, LapRecord, ModelExtractionAttempt, RaceSession, WeatherType
from forza.application import DatabaseService
from forza.application.rebuild_service import RebuildService
from forza.db import create_sqlite_engine
from forza.db.models import ExportArtifactEntity, LapRecordEntity, ReviewCaseEntity, ReviewCorrectionEntity
from forza.application import GuiWriteService
from sqlmodel import Session, select


GAMERTAG = "Bujica89"
TRACK = "Lime Rock Park Full Circuit"


def _make_cfg(tmp_path: Path):
    cfg = load_config(tmp_path / "missing.ini")
    return dataclasses.replace(
        cfg,
        database_file=tmp_path / "forza.sqlite3",
        pdf_file=tmp_path / "output" / "forza_bestlaps.pdf",
        gamertag=GAMERTAG,
    )


def _make_refs(tmp_path: Path) -> ReferenceData:
    tracks = tmp_path / "tracks.txt"
    cars = tmp_path / "cars.txt"
    tracks.write_text(f"{TRACK}\n", encoding="utf-8")
    cars.write_text("Mazda MX-5 '90\n", encoding="utf-8")
    return load_reference_seed_text_data(tracks, cars)


def _seed(db_path: Path, *, dirty: bool = False) -> None:
    lap = LapRecord(GAMERTAG, "Mazda MX-5 '90", "D", "00:56.092", 56092, dirty)
    session = RaceSession(TRACK, 76.0, 24.4, [lap], "D", WeatherType.DRY)
    result = ExtractionResult(
        "Track - D #1.png",
        "hash-seed",
        session,
        "ok",
        model_attempts=[ModelExtractionAttempt(attempt_number=1, status="ok", accepted=True)],
    )
    with DatabaseService(db_path, auto_upgrade=True) as db:
        db.begin_run(
            run_id="run-1",
            backend="lmstudio",
            model="qwen",
            prompt_name="test",
            input_dir="input",
        )
        db.upsert_image_and_laps(result, run_id="run-1", gamertag=GAMERTAG)
        db.complete_run("run-1", metrics={"processed": 1, "succeeded": 1})


log = logging.getLogger("forza")


# ── Core behaviour ────────────────────────────────────────────────────────────

def test_rebuild_outputs_marks_best_laps_without_generating_pdf(tmp_path):
    cfg = _make_cfg(tmp_path)
    refs = _make_refs(tmp_path)
    _seed(cfg.database_file)

    service = RebuildService()
    cases = service.rebuild_outputs(cfg, refs, log)

    assert cases == []
    with DatabaseService(cfg.database_file, auto_upgrade=True) as db:
        assert db.count_best_laps() == 1
    assert not cfg.pdf_file.exists()


def test_rebuild_outputs_returns_list_of_review_cases(tmp_path):
    cfg = _make_cfg(tmp_path)
    refs = _make_refs(tmp_path)
    _seed(cfg.database_file, dirty=True)

    service = RebuildService()
    cases = service.rebuild_outputs(cfg, refs, log)

    assert isinstance(cases, list)
    # Dirty lap -> at least one review case
    assert len(cases) >= 1
    assert any(c.reason == "dirty_lap" for c in cases)


def test_rebuild_reapplies_stable_review_corrections_before_review_refresh(tmp_path):
    cfg = _make_cfg(tmp_path)
    refs = _make_refs(tmp_path)
    _seed(cfg.database_file, dirty=True)

    first_cases = RebuildService().rebuild_outputs(cfg, refs, log)

    dirty_case = next(case for case in first_cases if case.reason == "dirty_lap")
    with Session(create_sqlite_engine(cfg.database_file)) as session:
        case_row = session.exec(
            select(ReviewCaseEntity).where(ReviewCaseEntity.reason == "dirty_lap")
        ).one()
        lap_id = case_row.lap_record_id
    GuiWriteService(cfg.database_file).resolve_review_case_with_decision(
        case_row.id,
        lap_record_id=lap_id,
        decision={"field": "dirty", "value": False},
    )

    with Session(create_sqlite_engine(cfg.database_file)) as session:
        correction = session.exec(select(ReviewCorrectionEntity)).one()
        lap = session.get(LapRecordEntity, lap_id)
        assert correction.field == "dirty"
        assert lap is not None
        lap.dirty = True
        lap.best_lap = "00:56.092▲"
        session.add(lap)
        session.commit()

    cases = RebuildService().rebuild_outputs(cfg, refs, log)

    with Session(create_sqlite_engine(cfg.database_file)) as session:
        lap = session.get(LapRecordEntity, lap_id)
        open_dirty_cases = session.exec(
            select(ReviewCaseEntity).where(
                ReviewCaseEntity.reason == "dirty_lap",
                ReviewCaseEntity.status == "open",
            )
        ).all()

    assert lap is not None
    assert lap.dirty is False
    assert lap.best_lap == "00:56.092"
    assert not any(case.reason == "dirty_lap" for case in cases)
    assert open_dirty_cases == []


def test_rebuild_outputs_does_not_record_pdf_artifact(tmp_path):
    cfg = _make_cfg(tmp_path)
    refs = _make_refs(tmp_path)
    _seed(cfg.database_file)

    RebuildService().rebuild_outputs(cfg, refs, log)

    with DatabaseService(cfg.database_file, auto_upgrade=True) as db:
        status = db.status()
        with Session(db._engine_for_db()) as session:
            artifacts = session.exec(select(ExportArtifactEntity)).all()
    assert status.extraction_runs == 1  # seed run still present, not duplicated
    assert artifacts == []


def test_rebuild_outputs_does_not_use_load_runtime_history(tmp_path):
    """load_runtime_history was removed from RebuildService after the refactor;
    rebuild_outputs reads from SQL directly via DatabaseService."""
    assert not hasattr(RebuildService, "load_runtime_history"), (
        "load_runtime_history must not exist on RebuildService — "
        "rebuild_outputs reads from SQL directly"
    )


def test_rebuild_outputs_returns_empty_list_for_empty_database(tmp_path):
    cfg = _make_cfg(tmp_path)
    refs = _make_refs(tmp_path)
    # Bootstrap DB with no results
    with DatabaseService(cfg.database_file, auto_upgrade=True) as db:
        db.begin_run(run_id="empty-run", backend="lmstudio", model="qwen",
                     prompt_name="test", input_dir="input")
        db.complete_run("empty-run", metrics={"processed": 0, "succeeded": 0})

    cases = RebuildService().rebuild_outputs(cfg, refs, log)

    assert cases == []


def test_rebuild_service_has_no_external_record_loader_side_channel() -> None:
    assert not hasattr(RebuildService, "load_external_records")
