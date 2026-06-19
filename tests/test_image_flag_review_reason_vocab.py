from __future__ import annotations

from sqlmodel import Session, select

from forza.db import create_sqlite_engine
from forza.db.migrate import upgrade_database
from forza.db.models import ImageFlagEntity
from forza.db.repositories import ImageFileRepository, ImageFlagRepository


def test_image_flags_accept_all_review_reasons_including_driver_name(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    upgrade_database(db_path)
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            image = ImageFileRepository(session).upsert(
                image_id="img-1",
                file_hash="hash-1",
                file_name="raw.png",
                current_name="raw.png",
                current_path="raw.png",
            )
            for reason in (
                "dirty_lap",
                "track",
                "weather",
                "race_class",
                "car",
                "driver_name",
            ):
                ImageFlagRepository(session).add_flag(
                    image_file_id=image.id,
                    flag=reason,
                    reason=reason,
                )
            session.commit()

            flags = session.exec(select(ImageFlagEntity.flag_type).order_by(ImageFlagEntity.flag_type)).all()
    finally:
        engine.dispose()

    assert "driver_name" in flags
    assert "gamertag" not in flags
    assert "driver_name_invalid" not in flags
    assert "track_uncertain" not in flags
    assert "class_uncertain" not in flags
