from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, text
from sqlmodel import Session, select

from .contracts import DbDoctorCheck
from ...db.models import LapRecordEntity, ImageFileEntity
from ...pipeline import file_hash


def image_file_checks(session: Session) -> list[DbDoctorCheck]:
    missing_available_files, mismatched_available_hashes = _available_image_file_checks(session)
    return [
        DbDoctorCheck(
            "images_missing_metadata",
            "warning",
            _count(session, select(ImageFileEntity).where(
                (ImageFileEntity.size_bytes.is_(None))
                | (ImageFileEntity.width_px.is_(None))
                | (ImageFileEntity.height_px.is_(None))
            )),
            "Image files without physical metadata.",
        ),
        _check_sql(
            session,
            key="available_image_path_conflicts",
            detail="An available current_path may identify only one image file.",
            sql="""
                SELECT current_path
                FROM image_files
                WHERE file_status = 'available' AND current_path IS NOT NULL
                GROUP BY current_path
                HAVING COUNT(*) > 1
            """,
            count_groups=True,
        ),
        DbDoctorCheck(
            "available_images_missing_files",
            "error",
            missing_available_files,
            "Available image files must resolve to an existing current_path file.",
        ),
        DbDoctorCheck(
            "available_images_hash_mismatch",
            "error",
            mismatched_available_hashes,
            "Available image file bytes must match their persisted file_hash.",
        ),
    ]


def best_lap_value_checks(session: Session) -> list[DbDoctorCheck]:
    return [
        _check_sql(
            session,
            key="best_laps_without_positive_ms",
            detail="Rows marked as best laps must have positive best_lap_ms values.",
            sql="""
                SELECT
                    (SELECT COUNT(*)
                     FROM lap_records
                     WHERE is_best_lap = 1
                       AND COALESCE(best_lap_ms, 0) <= 0)
                  + (SELECT COUNT(*)
                     FROM external_lap_records
                     WHERE active = 1
                       AND COALESCE(best_lap_ms, 0) <= 0)
            """,
        ),
        _check_sql(
            session,
            key="clean_lap_contains_dirty_marker",
            detail="Clean canonical lap times must not retain dirty-lap markers.",
            sql="""
                SELECT COUNT(*)
                FROM lap_records
                WHERE dirty = 0
                  AND (
                      best_lap LIKE '%▲%'
                      OR best_lap LIKE '%⚠%'
                      OR best_lap LIKE '%†%'
                  )
            """,
        ),
    ]


def lap_parent_checks(session: Session) -> list[DbDoctorCheck]:
    return [
        DbDoctorCheck(
            "laps_without_image_file",
            "error",
            _count(session, select(LapRecordEntity).where(
                ~LapRecordEntity.image_file_id.in_(select(ImageFileEntity.id)),
            )),
            "Lap rows whose image file no longer exists.",
        ),
        _check_sql(
            session,
            key="lap_parent_mismatch",
            detail="Lap run/source links must match their extraction_result.",
            sql="""
                SELECT COUNT(*)
                FROM lap_records l
                JOIN extraction_results er ON er.id = l.extraction_result_id
                WHERE l.run_id IS NOT er.run_id
                   OR l.image_file_id IS NOT er.image_file_id
            """,
        ),
    ]


def best_lap_status_checks(session: Session) -> list[DbDoctorCheck]:
    return [
        DbDoctorCheck(
            "best_lap_status_divergent",
            "warning",
            _best_status_divergence(session),
            "Images marked as contributing without a best lap, or the reverse.",
        ),
        DbDoctorCheck(
            "best_lap_status_stale_pending",
            "error",
            _pending_images_with_clean_laps(session),
            "Images with clean lap rows must not remain in pending best-lap status.",
        ),
    ]


def _count(session: Session, query) -> int:
    return int(session.exec(select(func.count()).select_from(query.subquery())).one())


def _scalar_sql(session: Session, sql: str) -> int:
    row = session.exec(text(sql)).one()
    return int(row[0] if isinstance(row, tuple) or hasattr(row, "__getitem__") else row)


def _check_sql(
    session: Session,
    *,
    key: str,
    detail: str,
    sql: str,
    severity: str = "error",
    count_groups: bool = False,
) -> DbDoctorCheck:
    if count_groups:
        rows = session.exec(text(sql)).all()
        count = len(rows)
    else:
        count = _scalar_sql(session, sql)
    return DbDoctorCheck(key, severity, count, detail)


def _available_image_file_checks(session: Session) -> tuple[int, int]:
    missing = 0
    mismatched = 0
    rows = session.exec(
        select(ImageFileEntity.current_path, ImageFileEntity.file_hash).where(
            ImageFileEntity.file_status == "available"
        )
    ).all()
    for current_path, expected_hash in rows:
        path = Path(current_path) if current_path else None
        if path is None:
            missing += 1
            continue
        try:
            stat = path.stat()
        except OSError:
            missing += 1
            continue
        if not path.is_file():
            missing += 1
            continue
        expected_size = _size_from_file_hash(expected_hash)
        if expected_size is not None and stat.st_size != expected_size:
            mismatched += 1
            continue
        try:
            actual_hash = file_hash(path)
        except OSError:
            missing += 1
            continue
        if actual_hash != expected_hash:
            mismatched += 1
    return missing, mismatched


def _size_from_file_hash(value: str | None) -> int | None:
    if not value or "_" not in value:
        return None
    _hash_part, size_text = value.rsplit("_", 1)
    try:
        return int(size_text)
    except ValueError:
        return None


def _best_status_divergence(session: Session) -> int:
    image_ids_with_best = {
        value for value in session.exec(
            select(LapRecordEntity.image_file_id).where(LapRecordEntity.is_best_lap == True)  # noqa: E712
        ).all()
    }
    rows = session.exec(select(ImageFileEntity.id, ImageFileEntity.best_lap_status)).all()
    divergent = 0
    for image_id, status in rows:
        has_best = image_id in image_ids_with_best
        contributing = status == "contributing"
        if has_best != contributing:
            divergent += 1
    return divergent


def _pending_images_with_clean_laps(session: Session) -> int:
    return _scalar_sql(
        session,
        """
        SELECT COUNT(DISTINCT si.id)
        FROM image_files si
        JOIN lap_records lr ON lr.image_file_id = si.id
        WHERE si.best_lap_status = 'pending'
          AND si.file_status = 'available'
          AND lr.dirty = 0
          AND COALESCE(lr.best_lap_ms, 0) > 0
        """,
    )
