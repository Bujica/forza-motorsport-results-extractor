import dataclasses
import sqlite3
from pathlib import Path

from forza.config import load_config
from forza.schemas import (
    ExtractionResult,
    ExtractionStatus,
    ImageFlagStatus,
    LapRecord,
    ModelExtractionAttempt,
    RaceSession,
    ReviewCaseStatus,
    ImageFileStatus,
    WeatherType,
    dump_schema,
)
from forza.application import (
    DatabaseService,
    ExportService,
)



def _seed_runtime_results(
    database: DatabaseService,
    run_id: str,
    results: list[ExtractionResult],
    *,
    gamertag: str = "Bujica89",
) -> None:
    database.begin_run(
        run_id=run_id,
        backend="lmstudio",
        model="test-model",
        prompt_name="test",
        input_dir="input",
    )
    for result in results:
        if result.status == "ok" and not result.model_attempts:
            result.model_attempts = [
                ModelExtractionAttempt(attempt_number=1, status="ok", accepted=True)
            ]
        database.upsert_image_and_laps(result, run_id=run_id, gamertag=gamertag)
    database.recompute_best_laps(run_id=run_id, gamertag=gamertag)
    database.complete_run(
        run_id,
        metrics={"processed": len(results), "succeeded": len(results)},
    )



def test_schema_serialization_uses_plain_enum_values():
    lap = LapRecord("Bujica89", "Mazda MX-5 '90", "D", "00:56.092", 56092)
    session = RaceSession(
        "Lime Rock Park Full Circuit",
        76.0,
        24.4,
        [lap],
        "D",
        WeatherType.DRY,
    )
    result = ExtractionResult("image.png", "hash", session, ExtractionStatus.OK)

    data = dump_schema(result)

    assert data["status"] == "ok"
    assert data["session"]["weather"] == "dry"
    assert data["session"]["entries"][0]["dirty"] is False


def test_state_enums_cover_persisted_db_contract_vocabulary():
    assert {status.value for status in ImageFileStatus} == {
        "available",
        "missing",
    }
    assert {status.value for status in ImageFlagStatus} == {
        "active",
        "resolved",
        "ignored",
    }
    assert {status.value for status in ReviewCaseStatus} == {
        "open",
        "resolved",
        "ignored",
        "auto_resolved",
    }



def test_export_service_writes_clean_cache_csv(tmp_path: Path):
    cfg = load_config(tmp_path / "missing.ini")
    cfg = dataclasses.replace(
        cfg,
        database_file=tmp_path / "forza.sqlite3",
        gamertag="Bujica89",
    )
    lap = LapRecord("Bujica89", "Mazda MX-5 '90", "D", "00:56.092", 56092)
    session = RaceSession(
        "Lime Rock Park Full Circuit",
        76.0,
        24.4,
        [lap],
        "D",
        WeatherType.DRY,
    )
    result = ExtractionResult("Track - D #1.png", "hash", session, "ok")
    with DatabaseService(cfg.database_file, auto_upgrade=True) as database:
        _seed_runtime_results(database, "export_run", [result], gamertag=cfg.gamertag)

    rows = ExportService().clean_csv(cfg, tmp_path / "results.csv")

    assert rows == 1



def test_database_clean_results_persists_dirty_best_lap_recompute(tmp_path: Path):
    cfg = load_config(tmp_path / "missing.ini")
    cfg = dataclasses.replace(
        cfg,
        database_file=tmp_path / "forza.sqlite3",
        gamertag="Bujica89",
    )
    lap = LapRecord("Bujica89", "Mazda MX-5 '90", "D", "00:56.092▲", 56092, True)
    session = RaceSession(
        "Lime Rock Park Full Circuit",
        76.0,
        24.4,
        [lap],
        "D",
        WeatherType.DRY,
    )
    result = ExtractionResult("Track - D #1.png", "hash-dirty", session, "ok")
    with DatabaseService(cfg.database_file, auto_upgrade=True) as database:
        _seed_runtime_results(database, "dirty_best_run", [result], gamertag=cfg.gamertag)

    with sqlite3.connect(cfg.database_file) as con:
        con.execute("update lap_records set is_best_lap = 0")

    with DatabaseService(cfg.database_file, auto_upgrade=True) as database:
        clean_before = database.list_clean_flat()
        recomputed = database.recompute_best_laps(gamertag=cfg.gamertag)
        clean = database.list_clean_flat()

    assert clean_before == []
    assert recomputed == 1
    assert sum(1 for item in clean if item.dirty) == 1
    with sqlite3.connect(cfg.database_file) as con:
        persisted = con.execute(
            "select count(*) from lap_records where dirty = 1 and is_best_lap = 1"
        ).fetchone()[0]
    assert persisted == 1



def test_review_service_persists_sql_cases_with_lap_linkage(tmp_path: Path):
    cfg = load_config(tmp_path / "missing.ini")
    cfg = dataclasses.replace(
        cfg,
        database_file=tmp_path / "forza.sqlite3",
    )
    lap = LapRecord(
        "Bujica89",
        "Mazda MX-5 '90",
        "D",
        "00:56.092▲",
        56092,
        dirty=True,
    )
    session = RaceSession(
        "Lime Rock Park Full Circuit",
        76.0,
        24.4,
        [lap],
        "D",
        WeatherType.DRY,
    )
    results = [ExtractionResult("Track - D #1.png", "hash", session, "ok")]
    with DatabaseService(cfg.database_file, auto_upgrade=True) as database:
        _seed_runtime_results(database, "review_run", results, gamertag=cfg.gamertag)
    with sqlite3.connect(cfg.database_file) as con:
        con.execute("update lap_records set is_best_lap = 1 where dirty = 1")
    with DatabaseService(cfg.database_file, auto_upgrade=True) as database:
        first = database.refresh_review_cases(run_id="review_run")

    assert first == (1, 0, 0)
    with DatabaseService(cfg.database_file, auto_upgrade=True) as database:
        cases = database.status().review_cases
        assert cases == 1


