from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from forza.application import DatabaseService
from forza.db import session_scope
from forza.db.models import (
    ExportArtifactEntity,
    ExternalRecordImportEntity,
    ExternalLapRecordEntity,
    ExtractionAttemptEntity,
    ExtractionRunEntity,
    ImageFlagEntity,
    LapRecordEntity,
    ModelArtifactEntity,
    ModelRuntimeSnapshotEntity,
    PromptSnapshotEntity,
    ReferenceCarEntity,
    ReferenceTrackEntity,
    ReviewCaseEntity,
    ReviewCorrectionEntity,
    RunInputEntity,
    ImageFileEntity,
)
from forza.db.repositories import (
    ExportArtifactRepository,
    ExternalRecordRepository,
    ExtractionResultRepository,
    LapRepository,
    ReviewRepository,
    RunRepository,
    ImageFileRepository,
)
from forza.schemas import (
    BestLapStatus,
    ExternalLapRecord,
    ExtractionResult,
    ImageMetadata,
    LapRecord,
    ModelExtractionAttempt,
    ModelResponseStats,
    RaceClass,
    RaceSession,
    ReviewCase,
    ReviewDecisionField,
    ReviewOutcome,
    ReviewReason,
    ReviewTrigger,
    ImageFile,
    ImageFileStatus,
    WeatherType,
    dump_schema,
)
from pydantic import ValidationError

from tests._db_repository_helpers import (
    REL_GAMERTAG,
    REL_TRACK,
    _rel_entry,
    _rel_result,
    _seed_runtime_results,
    make_engine,
    make_result,
)

def test_external_record_import_totals_use_columns(tmp_path):
    engine = make_engine(tmp_path)

    records = [
        ExternalLapRecord(
            track="Lime Rock Park Full Circuit",
            race_class="D",
            driver="Bujica89",
            car="Mazda MX-5 '90",
            best_lap="00:56.092",
            best_lap_ms=56092,
        )
    ]
    issues = [{"kind": "invalid_lap", "value": "bad", "detail": "row 2"}]

    with Session(engine) as session:
        import_row = ExternalRecordRepository(session).replace_active_snapshot(
            records,
            source_path=str(tmp_path / "records.csv"),
            source_hash="hash-records",
            total_rows=2,
            issues=issues,
            import_id="external-import-columns",
        )
        session.commit()

        persisted = session.get(ExternalRecordImportEntity, import_row.id)

    assert persisted is not None
    assert persisted.total_rows == 2
    assert persisted.accepted_rows == 1
    assert persisted.rejected_rows == 1
    assert persisted.issue_count == 1
    assert persisted.issues_json == issues


def test_external_record_snapshot_marks_import_and_records_active_dry(tmp_path):
    engine = make_engine(tmp_path)

    records = [
        ExternalLapRecord(
            track="Lime Rock Park Full Circuit",
            race_class="D",
            driver="KSR Planet",
            car="Donkervoort GTO",
            best_lap="00:55.934",
            best_lap_ms=55934,
        )
    ]

    with Session(engine) as session:
        import_row = ExternalRecordRepository(session).replace_active_snapshot(
            records,
            source_path=str(tmp_path / "records.xlsx"),
            source_hash="hash-records",
            total_rows=1,
            import_id="external-import-active-dry",
        )
        session.commit()

        persisted_import = session.get(ExternalRecordImportEntity, import_row.id)
        persisted_records = session.exec(select(ExternalLapRecordEntity)).all()

    assert persisted_import is not None
    assert persisted_import.status == "active"
    assert persisted_import.active is True
    assert len(persisted_records) == 1
    assert persisted_records[0].active is True
    assert persisted_records[0].weather == "dry"


def test_external_record_snapshot_deactivates_previous_active_import(tmp_path):
    engine = make_engine(tmp_path)
    first = [
        ExternalLapRecord(
            track="Lime Rock Park Full Circuit",
            race_class="D",
            driver="Driver One",
            car="Mazda MX-5 '90",
            best_lap="00:56.000",
            best_lap_ms=56000,
        )
    ]
    second = [
        ExternalLapRecord(
            track="Mugello Circuit Full Circuit",
            race_class="S",
            driver="Driver Two",
            car="Ferrari F40 Competizione",
            best_lap="01:45.000",
            best_lap_ms=105000,
        )
    ]

    with Session(engine) as session:
        repo = ExternalRecordRepository(session)
        first_import = repo.replace_active_snapshot(
            first,
            source_path=str(tmp_path / "first.xlsx"),
            import_id="external-import-first",
        )
        second_import = repo.replace_active_snapshot(
            second,
            source_path=str(tmp_path / "second.xlsx"),
            import_id="external-import-second",
        )
        session.commit()

        old_import = session.get(ExternalRecordImportEntity, first_import.id)
        new_import = session.get(ExternalRecordImportEntity, second_import.id)
        active_records = session.exec(
            select(ExternalLapRecordEntity).where(ExternalLapRecordEntity.active == True)  # noqa: E712
        ).all()

    assert old_import is not None
    assert new_import is not None
    assert old_import.active is False
    assert new_import.active is True
    assert len(active_records) == 1
    assert active_records[0].track == "Mugello Circuit Full Circuit"
    assert active_records[0].weather == "dry"


def test_external_record_import_rejected_rows_ignore_nonfatal_warnings(tmp_path):
    engine = make_engine(tmp_path)
    records = [
        ExternalLapRecord(
            track="Lime Rock Park Full Circuit",
            race_class="D",
            driver="Bujica89",
            car="Mazda MX-5 '90",
            best_lap="00:56.092",
            best_lap_ms=56092,
        )
    ]
    issues = [
        {"kind": "new_car", "value": "New Car", "detail": "row 2"},
        {"kind": "car_alias_canonicalized", "value": "Mini Cooper '65", "detail": "MINI Cooper '65"},
        {"kind": "invalid_lap", "value": "bad", "detail": "row 3"},
    ]

    with Session(engine) as session:
        import_row = ExternalRecordRepository(session).replace_active_snapshot(
            records,
            source_path=str(tmp_path / "records.csv"),
            source_hash="hash-records",
            total_rows=3,
            issues=issues,
            import_id="external-import-warning-counts",
        )
        session.commit()

        persisted = session.get(ExternalRecordImportEntity, import_row.id)

    assert persisted is not None
    assert persisted.total_rows == 3
    assert persisted.accepted_rows == 1
    assert persisted.rejected_rows == 1
    assert persisted.issue_count == 3
    assert persisted.issues_json == issues
