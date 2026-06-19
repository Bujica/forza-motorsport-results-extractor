from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlmodel import Session, select

from ...domain.lap import strip_dirty_symbol
from ..models import LapRecordEntity, ReviewCaseEntity, ReviewCorrectionEntity

_FIELD_ALIASES = {"gamertag": "driver"}


class ReviewCorrectionRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert_from_case(
        self,
        case: ReviewCaseEntity,
        *,
        cause: str = "unknown",
    ) -> ReviewCorrectionEntity | None:
        if case.outcome != "model_error":
            return None
        if not case.image_file_id or not case.decision_field or case.corrected_value is None:
            return None

        field = _correction_field(case.decision_field)
        lap_index = case.lap_index if field in {"dirty", "car", "driver"} else None
        if lap_index is None and field in {"dirty", "car", "driver"} and case.lap_record_id:
            lap = self.session.get(LapRecordEntity, case.lap_record_id)
            lap_index = lap.lap_index if lap is not None else None
            case.lap_index = lap_index
        if lap_index is None and field in {"dirty", "car", "driver"}:
            return None
        stable_key = _stable_key(case.image_file_id, lap_index, field)
        existing = self.session.exec(
            select(ReviewCorrectionEntity).where(ReviewCorrectionEntity.stable_key == stable_key)
        ).first()
        now = datetime.now(timezone.utc)
        entity = existing or ReviewCorrectionEntity(
            id=uuid4().hex,
            stable_key=stable_key,
            image_file_id=case.image_file_id,
            lap_index=lap_index,
            field=field,
            corrected_value=case.corrected_value,
        )
        entity.model_value = case.model_value
        entity.corrected_value = case.corrected_value
        entity.error_type = case.error_type
        entity.cause = cause
        entity.review_case_id = case.id
        entity.updated_at = now
        self.session.add(entity)
        return entity

    def apply_all(self) -> int:
        applied = 0
        rows = self.session.exec(select(ReviewCorrectionEntity)).all()
        for correction in rows:
            applied += self.apply(correction)
        return applied

    def apply(self, correction: ReviewCorrectionEntity) -> int:
        if correction.field in {"track", "weather", "race_class"}:
            laps = self.session.exec(
                select(LapRecordEntity).where(
                    LapRecordEntity.image_file_id == correction.image_file_id
                )
            ).all()
        else:
            if correction.lap_index is None:
                return 0
            laps = self.session.exec(
                select(LapRecordEntity).where(
                    LapRecordEntity.image_file_id == correction.image_file_id,
                    LapRecordEntity.lap_index == correction.lap_index,
                )
            ).all()

        for lap in laps:
            _apply_to_lap(lap, correction)
            self.session.add(lap)
        return len(laps)


def _correction_field(field: str) -> str:
    return _FIELD_ALIASES.get(field, field)


def _stable_key(image_file_id: str, lap_index: int | None, field: str) -> str:
    return f"{image_file_id}:{'' if lap_index is None else lap_index}:{field}"


def _apply_to_lap(lap: LapRecordEntity, correction: ReviewCorrectionEntity) -> None:
    value = correction.corrected_value
    if correction.field == "dirty":
        lap.dirty = _bool_value(value)
        if not lap.dirty:
            lap.best_lap = strip_dirty_symbol(lap.best_lap)
    elif correction.field == "track":
        lap.track = value
        lap.track_normalized = value.casefold()
    elif correction.field == "weather":
        lap.weather = value
    elif correction.field == "race_class":
        lap.race_class = value
    elif correction.field == "car":
        lap.car = value
        lap.car_normalized = value.casefold()
    elif correction.field == "driver":
        lap.driver = value
        lap.driver_normalized = value.casefold()


def _bool_value(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes", "y", "on"}
