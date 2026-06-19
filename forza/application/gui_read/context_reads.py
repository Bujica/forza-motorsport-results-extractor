from __future__ import annotations

from collections.abc import Sequence

from sqlmodel import Session, select

from ...db.models import (
    ExtractionAttemptEntity,
    ExtractionResultEntity,
    ExtractionRunEntity,
    ModelArtifactEntity,
)


def result_context_maps(
    session: Session,
    rows: Sequence[ExtractionResultEntity],
) -> tuple[dict[str, ExtractionRunEntity], dict[str, ExtractionAttemptEntity], dict[str, ModelArtifactEntity]]:
    """Load shared context rows for extraction-result GUI projections."""
    run_ids = {row.run_id for row in rows}
    attempt_ids = {row.accepted_attempt_id for row in rows if row.accepted_attempt_id}
    result_ids = {row.id for row in rows}
    runs = {
        row.id: row
        for row in session.exec(select(ExtractionRunEntity).where(ExtractionRunEntity.id.in_(run_ids))).all()
    } if run_ids else {}
    attempts = {
        row.id: row
        for row in session.exec(select(ExtractionAttemptEntity).where(ExtractionAttemptEntity.id.in_(attempt_ids))).all()
    } if attempt_ids else {}
    artifacts = {
        row.extraction_result_id: row
        for row in session.exec(
            select(ModelArtifactEntity).where(
                ModelArtifactEntity.extraction_result_id.in_(result_ids),
                ModelArtifactEntity.artifact_type == "raw_response",
                ModelArtifactEntity.is_canonical == True,  # noqa: E712
            )
        ).all()
    } if result_ids else {}
    return runs, attempts, artifacts
