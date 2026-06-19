from __future__ import annotations

from sqlmodel import select

from ...db.models import LapRecordEntity, ImageFileEntity
from .session_provider import GuiReadSessionProvider
from .types import GuiLap


class GuiLapReadQueries:
    """Read queries for GUI lap tables and best-lap filtered views."""

    def __init__(self, session_provider: GuiReadSessionProvider):
        self._session_provider = session_provider

    def list_laps(
        self,
        *,
        image_file_id: str | None = None,
        run_id: str | None = None,
        track: str | None = None,
        race_class: str | None = None,
        driver: str | None = None,
        best_only: bool | None = None,
        dirty: bool | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[GuiLap]:
        if not self._session_provider.can_read():
            return []
        with self._session_provider.session() as session:
            query = select(LapRecordEntity, ImageFileEntity).join(
                ImageFileEntity,
                ImageFileEntity.id == LapRecordEntity.image_file_id,
            )
            if image_file_id is not None:
                query = query.where(LapRecordEntity.image_file_id == image_file_id)
            if run_id is not None:
                query = query.where(LapRecordEntity.run_id == run_id)
            if track is not None:
                query = query.where(LapRecordEntity.track == track)
            if race_class is not None:
                query = query.where(LapRecordEntity.race_class == race_class)
            if driver is not None:
                query = query.where(LapRecordEntity.driver == driver)
            if best_only is not None:
                query = query.where(LapRecordEntity.is_best_lap == best_only)
            if dirty is not None:
                query = query.where(LapRecordEntity.dirty == dirty)
            if image_file_id is not None:
                order = (LapRecordEntity.image_file_id, LapRecordEntity.lap_index)
            elif best_only is True:
                order = (
                    LapRecordEntity.track,
                    LapRecordEntity.race_class,
                    LapRecordEntity.weather,
                    LapRecordEntity.best_lap_ms,
                    LapRecordEntity.driver,
                    LapRecordEntity.car,
                )
            else:
                order = (LapRecordEntity.track, LapRecordEntity.race_class, LapRecordEntity.best_lap_ms)
            query = query.order_by(*order).offset(max(offset, 0))
            if limit is not None:
                query = query.limit(max(limit, 0))
            rows = session.exec(query).all()
            return [_lap(lap, image) for lap, image in rows]


def _lap(row: LapRecordEntity, image: ImageFileEntity | None = None) -> GuiLap:
    source_file = (image.semantic_name or image.current_name) if image is not None else row.source_file
    return GuiLap(
        id=row.id,
        image_file_id=row.image_file_id,
        extraction_result_id=row.extraction_result_id,
        run_id=row.run_id,
        source_file=source_file or row.source_file,
        lap_index=row.lap_index,
        track=row.track,
        race_class=row.race_class,
        weather=row.weather,
        temp_f=row.temp_f,
        driver=row.driver,
        car=row.car,
        car_class=row.race_class,
        best_lap=row.best_lap,
        best_lap_ms=row.best_lap_ms,
        dirty=row.dirty,
        is_best_lap=row.is_best_lap,
        race_datetime=image.race_datetime if image else None,
        race_date=image.race_date if image else None,
        image_format=image.image_format if image else None,
    )
