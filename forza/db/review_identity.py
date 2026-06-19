from __future__ import annotations

from dataclasses import dataclass

from .models import ReviewCaseEntity
from ..schemas import ReviewCase


LAP_SCOPED_REASONS = {"dirty_lap", "car", "driver_name"}
IMAGE_SCOPED_REASONS = {"track", "weather", "race_class"}


@dataclass(frozen=True)
class ReviewIdentity:
    reason: str
    canonical_key: str


def case_business_key(case: ReviewCase) -> str:
    return case_identity(case).canonical_key


def case_identity(case: ReviewCase) -> ReviewIdentity:
    reason = str(case.reason)
    image_file_id = case.image_file_id or ""
    driver_normalized = _normalize(case.driver)
    canonical_key = _canonical_key(
        reason=reason,
        image_file_id=image_file_id,
        lap_index=getattr(case, "lap_index", None),
        driver_normalized=driver_normalized,
        source_file=case.source_file,
        best_lap=case.best_lap,
    )
    return ReviewIdentity(reason=reason, canonical_key=canonical_key)


def entity_identity(row: ReviewCaseEntity) -> ReviewIdentity:
    reason = str(row.reason)
    image_file_id = row.image_file_id or ""
    driver_normalized = _normalize(row.driver_normalized or row.driver)
    canonical_key = _canonical_key(
        reason=reason,
        image_file_id=image_file_id,
        lap_index=row.lap_index,
        driver_normalized=driver_normalized,
        source_file=row.source_file,
        best_lap=row.best_lap,
    )
    return ReviewIdentity(reason=reason, canonical_key=canonical_key)


def _canonical_key(
    *,
    reason: str,
    image_file_id: str,
    lap_index: int | None,
    driver_normalized: str,
    source_file: str | None,
    best_lap: str | None,
) -> str:
    if reason in LAP_SCOPED_REASONS and image_file_id:
        return f"{reason}:{image_file_id}:{'' if lap_index is None else lap_index}"
    if reason in IMAGE_SCOPED_REASONS and image_file_id:
        return f"{reason}:{image_file_id}"
    if image_file_id or driver_normalized:
        return f"{reason}:{image_file_id}:{'' if lap_index is None else lap_index}:{driver_normalized}"
    return f"{reason}:fallback:{source_file}:{driver_normalized}:{best_lap or ''}"


def _normalize(value: str | None) -> str:
    return str(value or "").strip().casefold()
