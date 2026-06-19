from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func
from sqlmodel import Session, select

from ..review_identity import case_business_key
from ..models import ReviewCaseEntity
from ...schemas import ReviewCase


class ReviewRepository:
    def __init__(self, session: Session):
        self.session = session

    def add_case(
        self,
        case: ReviewCase,
        *,
        lap_record_id: str | None = None,
    ) -> ReviewCaseEntity:
        entity = ReviewCaseEntity(
            id=uuid4().hex,
            image_file_id=case.image_file_id,
            run_id=case.run_id,
            extraction_result_id=case.extraction_result_id,
            lap_record_id=lap_record_id or case.lap_record_id,
            case_number=case.case_number,
            source_file=case.source_file,
            weather=str(case.weather),
            temp_f=case.temp_f,
            reason=str(case.reason),
            trigger=case.trigger,
            outcome=case.outcome,
            decision_field=case.decision_field,
            model_value=case.model_value,
            corrected_value=case.corrected_value,
            error_type=case.error_type,
            track=case.track,
            race_class=str(case.race_class),
            driver=case.driver,
            driver_normalized=str(case.driver or "").casefold() if case.driver is not None else None,
            car=case.car,
            car_normalized=str(case.car or "").casefold() if case.car is not None else None,
            best_lap=case.best_lap,
            lap_index=getattr(case, "lap_index", None),
            business_key=case_business_key(case),
            track_suggestions_json=case.track_suggestions,
        )
        self.session.add(entity)
        return entity

    def open_cases(self) -> list[ReviewCaseEntity]:
        return list(
            self.session.exec(
                select(ReviewCaseEntity).where(ReviewCaseEntity.status == "open")
            )
        )

    def upsert_review_cases(self, candidates: list[ReviewCase]) -> tuple[int, int, int]:
        """Refresh cases without deleting audit history or manual decisions.

        Returns ``(inserted, kept, removed)``. Open cases that are no longer
        detected become ``auto_resolved``; manually resolved/ignored rows are
        preserved. Auto-resolved cases reopen if the same stable key returns.
        """
        open_rows = self.open_cases()
        closed_rows = list(
            self.session.exec(
                select(ReviewCaseEntity).where(ReviewCaseEntity.status != "open")
            )
        )
        incoming_keys = {_case_key(case) for case in candidates}
        open_by_key = {_entity_key(row): row for row in open_rows}
        removed = 0
        for key, row in open_by_key.items():
            if key not in incoming_keys:
                row.status = "auto_resolved"
                row.resolved_at = datetime.now(timezone.utc)
                row.resolution_note = "no_longer_detected"
                row.updated_at = row.resolved_at
                self.session.add(row)
                removed += 1

        kept = len(open_rows) - removed
        next_case_number = self._next_case_number()
        inserted = 0
        processed_keys = set(open_by_key)
        for case in candidates:
            key = _case_key(case)
            if key in processed_keys:
                continue
            compatible_closed = [
                row for row in closed_rows
                if _entity_key(row) == key
            ]
            closed = sorted(compatible_closed, key=_closed_match_rank)[0] if compatible_closed else None
            if closed is not None:
                if closed.status == "auto_resolved":
                    closed.status = "open"
                    closed.resolved_at = None
                    closed.resolution_note = None
                    closed.updated_at = datetime.now(timezone.utc)
                    closed.lap_record_id = case.lap_record_id
                    closed.extraction_result_id = case.extraction_result_id
                    closed.run_id = case.run_id
                    closed.trigger = case.trigger
                    closed.model_value = case.model_value
                    closed.outcome = "pending"
                    closed.business_key = case_business_key(case)
                    self.session.add(closed)
                    kept += 1
                processed_keys.add(key)
                continue
            case.case_number = next_case_number
            next_case_number += 1
            self.add_case(case)
            processed_keys.add(key)
            inserted += 1
        return inserted, kept, removed

    def resolve(self, case_id: str) -> ReviewCaseEntity | None:
        entity = self.session.get(ReviewCaseEntity, case_id)
        if entity is None:
            return None
        entity.status = "resolved"
        entity.resolved_at = datetime.now(timezone.utc)
        self.session.add(entity)
        return entity

    def _next_case_number(self) -> int:
        value = self.session.exec(
            select(func.max(ReviewCaseEntity.case_number))
        ).one()
        return int(value or 0) + 1


def _case_key(case: ReviewCase) -> tuple[str, str]:
    return (str(case.reason), case_business_key(case))


def _entity_key(row: ReviewCaseEntity) -> tuple[str, str]:
    return (row.reason, row.business_key)


def _closed_match_rank(row: ReviewCaseEntity) -> int:
    if row.status in {"resolved", "ignored"}:
        return 0
    if row.status == "auto_resolved":
        return 1
    return 2
