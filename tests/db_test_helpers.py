from __future__ import annotations

from sqlalchemy import func
from sqlmodel import Session, select

from forza.db.models import ExtractionResultEntity, ExtractionRunEntity, RunInputEntity, ImageFileEntity


def add_extraction_result_parent(
    session: Session,
    *,
    run_id: str,
    image_file_id: str,
    result_id: str = "result-1",
    file_name: str = "raw.png",
    file_hash: str | None = None,
    status: str = "ok",
) -> ExtractionResultEntity:
    """Create the minimal FK parent chain required by lap_records.

    Tests often exercise GUI/write behavior by inserting LapRecordEntity rows
    directly. With SQLite FK enforcement enabled, those rows need a valid
    run_inputs row and extraction_results row first. This helper keeps that
    setup explicit instead of weakening runtime foreign-key enforcement.
    """
    if session.get(ExtractionRunEntity, run_id) is None:
        raise AssertionError(f"missing test extraction run: {run_id}")
    image = session.get(ImageFileEntity, image_file_id)
    if image is None:
        raise AssertionError(f"missing test image file: {image_file_id}")

    existing = session.get(ExtractionResultEntity, result_id)
    if existing is not None:
        return existing
    existing = session.exec(
        select(ExtractionResultEntity).where(
            ExtractionResultEntity.run_id == run_id,
            ExtractionResultEntity.image_file_id == image_file_id,
        )
    ).first()
    if existing is not None:
        return existing

    max_order = session.exec(
        select(func.max(RunInputEntity.input_order)).where(RunInputEntity.run_id == run_id)
    ).one()
    run_input = RunInputEntity(
        run_id=run_id,
        image_file_id=image_file_id,
        input_order=int(max_order if max_order is not None else -1) + 1,
        input_path=file_name,
        normalized_path=file_name,
        file_name=file_name,
        extension=".png",
        file_hash=file_hash or image.file_hash,
        decision="process",
        process_reason="test_fixture",
    )
    session.add(run_input)
    session.flush()

    result = ExtractionResultEntity(
        id=result_id,
        run_id=run_id,
        run_input_id=run_input.id,
        image_file_id=image_file_id,
        status=status,
    )
    session.add(result)
    session.flush()
    return result
