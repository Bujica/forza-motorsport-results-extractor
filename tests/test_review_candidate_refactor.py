from __future__ import annotations

from sqlmodel import Session, select

from forza.db.models import (
    ExtractionResultEntity,
    ImageFileEntity,
    LapRecordEntity,
    ReferenceCarEntity,
    ReferenceTrackEntity,
    RunInputEntity,
)
from forza.db.repositories import LapRepository, RunRepository
from tests._db_repository_helpers import make_engine


KNOWN_TRACK = "Lime Rock Park Full Circuit"
KNOWN_CAR = "Mazda MX-5 '90"


def _add_review_candidate_lap(
    session: Session,
    *,
    result_id: str,
    run_id: str,
    image_file_id: str,
    lap_index: int,
    track: str = KNOWN_TRACK,
    race_class: str = "D",
    weather: str = "dry",
    driver: str = "Bujica89",
    car: str = KNOWN_CAR,
    best_lap: str = "00:56.000",
    best_lap_ms: int = 56000,
    dirty: bool = False,
    is_best_lap: bool = False,
) -> LapRecordEntity:
    row = LapRecordEntity(
        id=f"{image_file_id}-lap-{lap_index}",
        extraction_result_id=result_id,
        run_id=run_id,
        image_file_id=image_file_id,
        source_file=f"{image_file_id}.png",
        lap_index=lap_index,
        track=track,
        track_normalized=track.casefold(),
        race_class=race_class,
        weather=weather,
        temp_f=76.0,
        driver=driver,
        driver_normalized=driver.casefold(),
        car=car,
        car_normalized=car.casefold(),
        best_lap=best_lap,
        best_lap_ms=best_lap_ms,
        dirty=dirty,
        is_best_lap=is_best_lap,
    )
    session.add(row)
    return row


def _seed_review_candidate_context(
    session: Session,
    *,
    run_id: str = "review-candidate-run",
    image_id: str = "review-candidate-image",
    result_id: str = "review-candidate-result",
    file_hash: str = "review-candidate-hash",
    file_name: str = "review-candidates.png",
) -> tuple[str, str, str]:
    run = RunRepository(session).by_id(run_id)
    if run is None:
        run = RunRepository(session).create(run_id=run_id, backend="lmstudio", model="qwen")
    image = ImageFileEntity(
        id=image_id,
        file_hash=file_hash,
        current_name=file_name,
        current_path=file_name,
    )
    session.add(image)
    session.flush()
    run_input = RunInputEntity(
        run_id=run.id,
        image_file_id=image.id,
        input_order=0,
        input_path=file_name,
        file_name=file_name,
        file_hash=image.file_hash,
        decision="process",
        process_reason="new",
    )
    session.add(run_input)
    session.flush()
    result = ExtractionResultEntity(
        id=result_id,
        run_id=run.id,
        run_input_id=run_input.id,
        image_file_id=image.id,
        status="ok",
    )
    session.add(result)
    session.flush()
    return run.id, image.id, result.id


def test_review_candidate_refactor_preserves_detected_reasons_and_ordering(tmp_path):
    engine = make_engine(tmp_path)

    with Session(engine) as session:
        session.add(ReferenceTrackEntity(id="track-known", name=KNOWN_TRACK))
        session.add(ReferenceCarEntity(id="car-known", name=KNOWN_CAR))
        run_id, image_file_id, result_id = _seed_review_candidate_context(session)
        _other_run_id, other_image_file_id, other_result_id = _seed_review_candidate_context(
            session,
            image_id="review-candidate-image-other-track",
            result_id="review-candidate-result-other-track",
            file_hash="review-candidate-hash-other-track",
            file_name="review-candidates-other-track.png",
        )
        _rain_run_id, rain_image_file_id, rain_result_id = _seed_review_candidate_context(
            session,
            image_id="review-candidate-image-rain",
            result_id="review-candidate-result-rain",
            file_hash="review-candidate-hash-rain",
            file_name="review-candidates-rain.png",
        )
        dirty_best = _add_review_candidate_lap(
            session,
            result_id=result_id,
            run_id=run_id,
            image_file_id=image_file_id,
            lap_index=0,
            dirty=True,
            is_best_lap=True,
        )
        dirty_non_best = _add_review_candidate_lap(
            session,
            result_id=result_id,
            run_id=run_id,
            image_file_id=image_file_id,
            lap_index=1,
            dirty=True,
            is_best_lap=False,
        )
        _add_review_candidate_lap(
            session,
            result_id=result_id,
            run_id=run_id,
            image_file_id=image_file_id,
            lap_index=2,
            weather="unknown",
        )
        _add_review_candidate_lap(
            session,
            result_id=result_id,
            run_id=run_id,
            image_file_id=image_file_id,
            lap_index=3,
            track="Unknown (ambiguous layout)",
        )
        _add_review_candidate_lap(
            session,
            result_id=result_id,
            run_id=run_id,
            image_file_id=image_file_id,
            lap_index=4,
            race_class="Prototype",
        )
        _add_review_candidate_lap(
            session,
            result_id=result_id,
            run_id=run_id,
            image_file_id=image_file_id,
            lap_index=5,
            driver="123 Driver",
        )
        _add_review_candidate_lap(
            session,
            result_id=result_id,
            run_id=run_id,
            image_file_id=image_file_id,
            lap_index=6,
            car="",
        )
        _add_review_candidate_lap(
            session,
            result_id=result_id,
            run_id=run_id,
            image_file_id=image_file_id,
            lap_index=7,
            car="Uncatalogued Car",
        )
        _add_review_candidate_lap(
            session,
            result_id=other_result_id,
            run_id=run_id,
            image_file_id=other_image_file_id,
            lap_index=0,
            track="Maple Valley Full Circuit",
        )
        _add_review_candidate_lap(
            session,
            result_id=rain_result_id,
            run_id=run_id,
            image_file_id=rain_image_file_id,
            lap_index=0,
            weather="dry",
            best_lap_ms=60000,
            is_best_lap=True,
        )
        _add_review_candidate_lap(
            session,
            result_id=rain_result_id,
            run_id=run_id,
            image_file_id=rain_image_file_id,
            lap_index=1,
            weather="rain",
            best_lap_ms=55000,
            is_best_lap=True,
        )
        dirty_best_id = dirty_best.id
        dirty_non_best_id = dirty_non_best.id
        session.commit()

        cases = LapRepository(session).query_review_candidates()

    reason_triggers = {(str(case.reason), str(case.trigger)) for case in cases}
    assert ("dirty_lap", "model_marked_dirty") in reason_triggers
    assert ("weather", "weather_unknown") in reason_triggers
    assert ("track", "track_unresolved") in reason_triggers
    assert ("track", "track_not_in_reference") in reason_triggers
    assert ("race_class", "class_invalid") in reason_triggers
    invalid_class_case = next(case for case in cases if str(case.reason) == "race_class")
    assert str(invalid_class_case.race_class) == "Unknown"
    assert invalid_class_case.model_value == "Prototype"
    assert ("driver_name", "numeric_prefix") in reason_triggers
    assert ("car", "car_empty") in reason_triggers
    assert ("car", "car_not_in_reference") in reason_triggers
    assert ("weather", "rain_time_suspicious") in reason_triggers
    assert any(case.reason == "dirty_lap" and case.lap_record_id == dirty_best_id for case in cases)
    assert not any(case.reason == "dirty_lap" and case.lap_record_id == dirty_non_best_id for case in cases)
    assert [case.case_number for case in cases] == list(range(1, len(cases) + 1))


def test_review_candidate_rows_prefilter_skips_clean_non_best_rows(tmp_path):
    engine = make_engine(tmp_path)

    with Session(engine) as session:
        session.add(ReferenceTrackEntity(id="track-known", name=KNOWN_TRACK))
        session.add(ReferenceCarEntity(id="car-known", name=KNOWN_CAR))
        run_id, image_file_id, result_id = _seed_review_candidate_context(session)
        clean = _add_review_candidate_lap(
            session,
            result_id=result_id,
            run_id=run_id,
            image_file_id=image_file_id,
            lap_index=0,
        )
        dirty_best = _add_review_candidate_lap(
            session,
            result_id=result_id,
            run_id=run_id,
            image_file_id=image_file_id,
            lap_index=1,
            dirty=True,
            is_best_lap=True,
        )
        clean_id = clean.id
        dirty_best_id = dirty_best.id
        session.commit()

        repo = LapRepository(session)
        context = repo._review_reference_context()
        rows = repo._review_candidate_rows(run_id=run_id, context=context)

    assert clean_id not in {row.id for row in rows}
    assert [row.id for row in rows] == [dirty_best_id]


def test_review_candidate_query_keeps_refactor_seams() -> None:
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "forza"
        / "db"
        / "repositories"
        / "laps.py"
    ).read_text(encoding="utf-8")

    assert "class _ReviewCaseCollector" in source
    assert "def _review_case_race_class" in source
    assert "def _review_candidate_rows" in source
    assert "def _review_candidate_row_ids" in source
    assert "def _sql_review_candidate_row_ids" in source
    assert "def _driver_review_candidate_row_ids" in source
    assert "def _base_review_candidate_condition" in source
    assert "LapRecordEntity.id.in_(candidate_ids)" in source
    assert "def _review_reference_context" in source
    assert "def _append_row_review_candidates" in source
    assert "def _append_rain_time_review_candidates" in source
    assert "def append(" not in source[source.index("def query_review_candidates"):source.index("def export_flat")]
