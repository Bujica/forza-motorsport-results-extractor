from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlmodel import Session, select

from ..models import ImageFlagEntity, LapRecordEntity


class ImageFlagRepository:
    def __init__(self, session: Session):
        self.session = session

    def add_flag(
        self,
        *,
        image_file_id: str,
        flag: str,
        run_id: str | None = None,
        extraction_result_id: str | None = None,
        lap_record_id: str | None = None,
        reason: str | None = None,
    ) -> ImageFlagEntity:
        lap = self.session.get(LapRecordEntity, lap_record_id) if lap_record_id else None
        flag_key = _flag_key(
            image_file_id=image_file_id,
            flag_type=flag,
            lap=lap,
        )
        existing = self.session.exec(
            select(ImageFlagEntity).where(ImageFlagEntity.flag_key == flag_key)
        ).first()
        if existing is not None:
            if existing.status == "resolved":
                existing.status = "active"
                existing.resolved_at = None
            existing.run_id = run_id
            existing.extraction_result_id = extraction_result_id
            existing.lap_record_id = lap_record_id
            existing.reason = reason
            self.session.add(existing)
            return existing
        entity = ImageFlagEntity(
            id=uuid4().hex,
            image_file_id=image_file_id,
            run_id=run_id,
            extraction_result_id=extraction_result_id,
            lap_record_id=lap_record_id,
            flag_key=flag_key,
            flag_scope="lap" if lap_record_id else "image",
            lap_index=lap.lap_index if lap is not None else None,
            driver_normalized=lap.driver_normalized if lap is not None else None,
            track_normalized=lap.track_normalized if lap is not None else None,
            race_class=lap.race_class if lap is not None else None,
            flag_type=flag,
            reason=reason,
        )
        self.session.add(entity)
        return entity

    def list_open(
        self,
        *,
        image_file_id: str | None = None,
        flag: str | None = None,
    ) -> list[ImageFlagEntity]:
        query = select(ImageFlagEntity).where(ImageFlagEntity.status == "active")
        if image_file_id is not None:
            query = query.where(ImageFlagEntity.image_file_id == image_file_id)
        if flag is not None:
            query = query.where(ImageFlagEntity.flag_type == flag)
        return list(self.session.exec(query.order_by(ImageFlagEntity.created_at.asc())))

    def resolve(self, flag_id: str) -> ImageFlagEntity | None:
        return self._set_status(flag_id, "resolved")

    def ignore(self, flag_id: str) -> ImageFlagEntity | None:
        return self._set_status(flag_id, "ignored")

    def _set_status(self, flag_id: str, status: str) -> ImageFlagEntity | None:
        entity = self.session.get(ImageFlagEntity, flag_id)
        if entity is None:
            return None
        entity.status = status
        entity.resolved_at = datetime.now(timezone.utc)
        self.session.add(entity)
        return entity


def _flag_key(*, image_file_id: str, flag_type: str, lap: LapRecordEntity | None = None) -> str:
    if lap is not None:
        return (
            f"lap:{image_file_id}:{flag_type}:{lap.lap_index}:"
            f"{lap.driver_normalized or ''}:{lap.track_normalized or ''}:{lap.race_class or ''}"
        )
    return f"image:{image_file_id}:{flag_type}"
