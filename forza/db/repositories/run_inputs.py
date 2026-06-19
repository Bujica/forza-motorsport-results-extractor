from __future__ import annotations

from pathlib import Path

from sqlalchemy import func
from sqlmodel import Session, select

from ...schemas import ExtractionResult
from ..models import RunInputEntity


def ensure_process_run_input(
    session: Session,
    result: ExtractionResult,
    *,
    run_id: str,
    image_file_id: str,
) -> int:
    existing = session.exec(
        select(RunInputEntity).where(
            RunInputEntity.run_id == run_id,
            RunInputEntity.image_file_id == image_file_id,
            RunInputEntity.decision == "process",
        )
    ).first()
    if existing is not None and existing.id is not None:
        return existing.id

    max_order = session.exec(
        select(func.max(RunInputEntity.input_order)).where(RunInputEntity.run_id == run_id)
    ).one()
    input_path = result.current_path or result.source_file
    path = Path(input_path)
    entity = RunInputEntity(
        run_id=run_id,
        image_file_id=image_file_id,
        input_order=int(max_order if max_order is not None else -1) + 1,
        input_path=str(input_path),
        normalized_path=str(path),
        file_name=path.name,
        extension=path.suffix.lower(),
        file_hash=result.file_hash,
        decision="process",
        process_reason="full_run",
    )
    session.add(entity)
    session.flush()
    if entity.id is None:
        raise RuntimeError("run_inputs insert did not produce an id")
    return entity.id
