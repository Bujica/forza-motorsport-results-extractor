from __future__ import annotations

from pathlib import Path

from forza.application import DatabaseService
from forza.db import create_sqlite_engine
from forza.db.testing import create_test_db_and_tables
from forza.schemas import ExtractionResult, LapRecord, ModelExtractionAttempt, RaceSession

def make_engine(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "forza.sqlite3")
    create_test_db_and_tables(engine)
    return engine

def make_result() -> ExtractionResult:
    entries = [
        LapRecord("Bujica89", "Mazda MX-5 '90", "D", "00:56.092", 56092, False),
        LapRecord("Driver2", "Honda Civic", "D", "00:55.500", 55500, True),
    ]
    session = RaceSession(
        "Lime Rock Park Full Circuit",
        76.0,
        24.4,
        entries,
        "D",
        "dry",
    )
    return ExtractionResult(
        "Lime Rock Park Full Circuit - D #1.png",
        "hash",
        session,
        "ok",
        model_attempts=[ModelExtractionAttempt(attempt_number=1, status="ok", accepted=True)],
    )

REL_GAMERTAG = "Bujica89"
REL_TRACK = "Silverstone Racing Circuit Grand Prix Circuit"

def _rel_entry(driver: str, car: str = "Test Car", car_class: str = "A", best_lap: str = "1:30.000", best_lap_ms: int = 90000, dirty: bool = False) -> LapRecord:
    return LapRecord(
        driver=driver,
        car=car,
        car_class=car_class,
        best_lap=best_lap,
        best_lap_ms=best_lap_ms,
        dirty=dirty,
    )

def _rel_result(source_file: str, file_hash: str, entries: list[LapRecord], *, temp_f: float = 77.0, weather: str = "dry") -> ExtractionResult:
    return ExtractionResult(
        source_file=source_file,
        file_hash=file_hash,
        semantic_name=source_file,
        current_path=source_file,
        session=RaceSession(
            track=REL_TRACK,
            temp_f=temp_f,
            temp_c=None,
            entries=entries,
            race_class="A",
            weather=weather,
        ),
        status="ok",
    )

def _seed_runtime_results(
    db: DatabaseService,
    run_id: str,
    results: list[ExtractionResult],
    *,
    gamertag: str = REL_GAMERTAG,
) -> None:
    db.begin_run(
        run_id=run_id,
        backend="lmstudio",
        model="qwen",
        prompt_name="test",
        input_dir="input",
    )
    for result in results:
        if result.status == "ok" and not result.model_attempts:
            result.model_attempts = [
                ModelExtractionAttempt(attempt_number=1, status="ok", accepted=True)
            ]
        db.upsert_image_and_laps(result, run_id=run_id, gamertag=gamertag)
    db.complete_run(
        run_id,
        metrics={"processed": len(results), "succeeded": len(results)},
    )
