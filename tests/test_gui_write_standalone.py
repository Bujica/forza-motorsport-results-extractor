"""Behavioural tests for GuiWriteService standalone lap-correction methods.

These tests call set_lap_dirty, set_lap_track, and set_lap_weather directly —
not via resolve_review_case_with_decision — which is the path used by
ReviewController when a lap_record_id is already known.
"""
from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, select

from forza.db import create_sqlite_engine
from forza.db.migrate import upgrade_database
from forza.db.models import LapRecordEntity, ImageFileEntity
from forza.db.repositories import RunRepository, ImageFileRepository
from forza.application import GuiWriteService
from tests.db_test_helpers import add_extraction_result_parent


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _seed(db_path: Path, image_path: Path) -> tuple[str, str, str]:
    """Return (image_id, lap_id_0, lap_id_1).

    Two laps from the same image file, different drivers, same group.
    """
    upgrade_database(db_path)
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            RunRepository(session).create(run_id="run-1", backend="test", model="m")
            image = ImageFileRepository(session).upsert(
                image_id="img-1",
                file_hash="hash-1",
                file_name=image_path.name,
                current_name=image_path.name,
                current_path=image_path,
            )
            add_extraction_result_parent(
                session,
                run_id="run-1",
                image_file_id=image.id,
                result_id="res-1",
                file_name=image_path.name,
                file_hash=image.file_hash,
            )
            lap0 = LapRecordEntity(
                id="lap-0",
                extraction_result_id="res-1",
                run_id="run-1",
                image_file_id=image.id,
                source_file=image_path.name,
                lap_index=0,
                track="Silverstone Racing Circuit Grand Prix Circuit",
                race_class="A",
                weather="dry",
                driver="Bujica89",
                car="BMW M4",
                best_lap="01:30.000",
                best_lap_ms=90000,
                dirty=True,
                is_best_lap=True,
            )
            lap1 = LapRecordEntity(
                id="lap-1",
                extraction_result_id="res-1",
                run_id="run-1",
                image_file_id=image.id,
                source_file=image_path.name,
                lap_index=1,
                track="Silverstone Racing Circuit Grand Prix Circuit",
                race_class="A",
                weather="dry",
                driver="Driver2",
                car="BMW M4",
                best_lap="01:31.000",
                best_lap_ms=91000,
                dirty=False,
                is_best_lap=True,
            )
            session.add(lap0)
            session.add(lap1)
            session.commit()
            return image.id, lap0.id, lap1.id
    finally:
        engine.dispose()


# ── set_lap_dirty ─────────────────────────────────────────────────────────────

def test_set_lap_dirty_clears_flag_and_emits_event(tmp_path):
    image_path = tmp_path / "raw.png"
    image_path.write_bytes(b"x")
    db_path = tmp_path / "forza.sqlite3"
    _, lap_id, _ = _seed(db_path, image_path)

    events = []
    service = GuiWriteService(db_path, event_sink=events.append)
    result = service.set_lap_dirty(lap_id, dirty=False)

    assert result is not None
    assert result.dirty is False

    # Persisted
    engine = create_sqlite_engine(db_path)
    with Session(engine) as session:
        row = session.get(LapRecordEntity, lap_id)
        assert row.dirty is False
    engine.dispose()

    assert any(e.type == "lap_record_corrected" for e in events)
    corrected = next(e for e in events if e.type == "lap_record_corrected")
    assert corrected.data["field"] == "dirty"
    assert corrected.data["value"] is False


def test_set_lap_dirty_returns_none_for_missing_lap(tmp_path):
    image_path = tmp_path / "raw.png"
    image_path.write_bytes(b"x")
    db_path = tmp_path / "forza.sqlite3"
    _seed(db_path, image_path)

    result = GuiWriteService(db_path).set_lap_dirty("nonexistent-id", dirty=True)
    assert result is None


# ── set_lap_weather ───────────────────────────────────────────────────────────

def test_set_lap_weather_normalizes_wet_to_rain(tmp_path):
    image_path = tmp_path / "raw.png"
    image_path.write_bytes(b"x")
    db_path = tmp_path / "forza.sqlite3"
    _, lap_id, _ = _seed(db_path, image_path)

    result = GuiWriteService(db_path).set_lap_weather(lap_id, "wet")

    assert result is not None
    assert result.weather == "rain"   # normalize_weather("wet") → "rain"

    engine = create_sqlite_engine(db_path)
    with Session(engine) as session:
        assert session.get(LapRecordEntity, lap_id).weather == "rain"
    engine.dispose()


def test_set_lap_weather_normalizes_cloudy_to_unknown(tmp_path):
    image_path = tmp_path / "raw.png"
    image_path.write_bytes(b"x")
    db_path = tmp_path / "forza.sqlite3"
    _, lap_id, _ = _seed(db_path, image_path)

    result = GuiWriteService(db_path).set_lap_weather(lap_id, "cloudy")

    assert result is not None
    assert result.weather == "unknown"


def test_set_lap_weather_updates_all_laps_of_image(tmp_path):
    """Weather correction must propagate to every lap from the same image file."""
    image_path = tmp_path / "raw.png"
    image_path.write_bytes(b"x")
    db_path = tmp_path / "forza.sqlite3"
    _, lap_id_0, lap_id_1 = _seed(db_path, image_path)

    GuiWriteService(db_path).set_lap_weather(lap_id_0, "rain")

    engine = create_sqlite_engine(db_path)
    with Session(engine) as session:
        laps = session.exec(select(LapRecordEntity)).all()
        assert all(lap.weather == "rain" for lap in laps)
    engine.dispose()


def test_set_lap_weather_invalidates_best_lap_group(tmp_path):
    """After weather change, is_best_lap must be cleared for the affected group."""
    image_path = tmp_path / "raw.png"
    image_path.write_bytes(b"x")
    db_path = tmp_path / "forza.sqlite3"
    image_id, lap_id_0, _ = _seed(db_path, image_path)

    GuiWriteService(db_path).set_lap_weather(lap_id_0, "rain")

    engine = create_sqlite_engine(db_path)
    with Session(engine) as session:
        laps = session.exec(select(LapRecordEntity)).all()
        assert all(not lap.is_best_lap for lap in laps)
        image = session.get(ImageFileEntity, image_id)
        assert image.best_lap_status == "pending"
    engine.dispose()


def test_set_lap_weather_canonical_value_is_written_verbatim(tmp_path):
    """'dry' is already canonical — no transformation, written as-is."""
    image_path = tmp_path / "raw.png"
    image_path.write_bytes(b"x")
    db_path = tmp_path / "forza.sqlite3"
    _, lap_id, _ = _seed(db_path, image_path)

    result = GuiWriteService(db_path).set_lap_weather(lap_id, "dry")

    assert result is not None
    assert result.weather == "dry"


# ── set_lap_track ─────────────────────────────────────────────────────────────

def test_set_lap_track_updates_all_laps_of_image(tmp_path):
    """Track correction must update every lap in the same image file."""
    image_path = tmp_path / "raw.png"
    image_path.write_bytes(b"x")
    db_path = tmp_path / "forza.sqlite3"
    _, lap_id_0, lap_id_1 = _seed(db_path, image_path)

    new_track = "Mugello Circuit Full Circuit"
    result = GuiWriteService(db_path).set_lap_track(lap_id_0, new_track)

    assert result is not None
    assert result.track == new_track

    engine = create_sqlite_engine(db_path)
    with Session(engine) as session:
        laps = session.exec(select(LapRecordEntity)).all()
        assert all(lap.track == new_track for lap in laps), \
            f"Expected all laps to have track={new_track!r}, got {[l.track for l in laps]}"
    engine.dispose()


def test_set_lap_track_invalidates_old_and_new_group(tmp_path):
    """Both the old and new (track, class, weather) groups must be invalidated."""
    image_path = tmp_path / "raw.png"
    image_path.write_bytes(b"x")
    db_path = tmp_path / "forza.sqlite3"
    image_id, lap_id_0, _ = _seed(db_path, image_path)

    GuiWriteService(db_path).set_lap_track(lap_id_0, "Mugello Circuit Full Circuit")

    engine = create_sqlite_engine(db_path)
    with Session(engine) as session:
        laps = session.exec(select(LapRecordEntity)).all()
        assert all(not lap.is_best_lap for lap in laps)
        image = session.get(ImageFileEntity, image_id)
        assert image.best_lap_status == "pending"
    engine.dispose()


def test_set_lap_track_emits_lap_record_corrected_event(tmp_path):
    image_path = tmp_path / "raw.png"
    image_path.write_bytes(b"x")
    db_path = tmp_path / "forza.sqlite3"
    _, lap_id, _ = _seed(db_path, image_path)

    events = []
    GuiWriteService(db_path, event_sink=events.append).set_lap_track(
        lap_id, "Mugello Circuit Full Circuit"
    )

    corrected = [e for e in events if e.type == "lap_record_corrected"]
    assert len(corrected) == 1
    assert corrected[0].data["field"] == "track"
    assert corrected[0].data["value"] == "Mugello Circuit Full Circuit"
