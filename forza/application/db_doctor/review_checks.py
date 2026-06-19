from __future__ import annotations

from sqlalchemy import func, text
from sqlmodel import Session, select

from .contracts import DbDoctorCheck
from ...db.models import ImageFlagEntity, LapRecordEntity, ReviewCaseEntity, ReviewCorrectionEntity, ImageFileEntity
from ...db.review_identity import entity_identity


def review_core_checks(session: Session) -> list[DbDoctorCheck]:
    return [
        _check_sql(
            session,
            key="open_reviews_missing_active_flag",
            detail="Every open review case must have a matching active image flag.",
            sql="""
                SELECT COUNT(*)
                FROM review_cases rc
                WHERE rc.status = 'open'
                  AND rc.image_file_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM image_flags f
                      WHERE f.image_file_id = rc.image_file_id
                        AND f.flag_type = rc.reason
                        AND COALESCE(f.lap_index, -1) = COALESCE(rc.lap_index, -1)
                        AND f.status = 'active'
                  )
            """,
        ),
        _check_sql(
            session,
            key="stale_active_review_flags",
            detail="System review flags must resolve when their review case disappears.",
            sql="""
                SELECT COUNT(*)
                FROM image_flags f
                WHERE f.status = 'active'
                  AND f.created_by = 'system'
                  AND f.flag_type IN (
                      'dirty_lap', 'track', 'weather',
                      'race_class', 'car', 'driver_name'
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM review_cases rc
                      WHERE rc.image_file_id = f.image_file_id
                        AND rc.reason = f.flag_type
                        AND COALESCE(rc.lap_index, -1) = COALESCE(f.lap_index, -1)
                        AND rc.status = 'open'
                  )
            """,
        ),
        _check_sql(
            session,
            key="review_cases_invalid_reason",
            detail="Review cases must use canonical reasons.",
            sql="""
                SELECT COUNT(*)
                FROM review_cases
                WHERE reason NOT IN (
                    'dirty_lap', 'track', 'weather',
                    'race_class', 'car', 'driver_name'
                )
            """,
        ),
        _check_sql(
            session,
            key="review_corrections_invalid",
            detail="Review corrections must use stable source/lap/field identity and valid field names.",
            sql="""
                SELECT COUNT(*)
                FROM review_corrections
                WHERE image_file_id IS NULL
                   OR stable_key IS NULL
                   OR stable_key = ''
                   OR corrected_value IS NULL
                   OR field NOT IN ('dirty', 'track', 'weather', 'race_class', 'car', 'driver')
                   OR (field IN ('dirty', 'car', 'driver') AND lap_index IS NULL)
                   OR (field IN ('track', 'weather', 'race_class') AND lap_index IS NOT NULL)
            """,
        ),
    ]


def review_model_error_identity_checks(session: Session) -> list[DbDoctorCheck]:
    return [
        _check_sql(
            session,
            key="model_error_missing_decision",
            detail="Model-error reviews must store the corrected field and values.",
            sql="""
                SELECT COUNT(*)
                FROM review_cases
                WHERE outcome = 'model_error'
                  AND (
                      decision_field IS NULL
                      OR corrected_value IS NULL
                      OR model_value IS NULL
                  )
            """,
        ),
        _check_sql(
            session,
            key="model_error_missing_raw_evidence",
            detail="Model-error reviews must remain linked to raw model evidence.",
            sql="""
                SELECT COUNT(*)
                FROM review_cases rc
                LEFT JOIN extraction_results er ON er.id = rc.extraction_result_id
                LEFT JOIN extraction_attempts a ON a.id = er.accepted_attempt_id
                WHERE rc.outcome = 'model_error'
                  AND (
                      er.id IS NULL
                      OR (
                          COALESCE(a.raw_response, '') = ''
                          AND NOT EXISTS (
                              SELECT 1 FROM model_artifacts ma
                              WHERE ma.extraction_result_id = er.id
                                AND ma.artifact_type = 'raw_response'
                                AND ma.is_canonical = 1
                          )
                      )
                  )
            """,
        ),
        DbDoctorCheck(
            "review_business_key_uses_lap_record_id",
            "error",
            _keys_containing_volatile_ids(session, ReviewCaseEntity, "business_key"),
            "review_cases.business_key must not depend on lap_record_id.",
        ),
        DbDoctorCheck(
            "review_business_key_not_canonical",
            "error",
            _noncanonical_review_business_keys(session),
            "review_cases.business_key must match the current canonical review identity.",
        ),
        DbDoctorCheck(
            "review_corrections_orphan_source",
            "error",
            _count(session, select(ReviewCorrectionEntity).where(
                ~ReviewCorrectionEntity.image_file_id.in_(select(ImageFileEntity.id)),
            )),
            "review_corrections.image_file_id must reference image_files.",
        ),
        DbDoctorCheck(
            "flag_key_uses_lap_record_id",
            "error",
            _keys_containing_volatile_ids(session, ImageFlagEntity, "flag_key"),
            "image_flags.flag_key must not depend on lap_record_id.",
        ),
    ]


def review_parent_flag_checks(session: Session) -> list[DbDoctorCheck]:
    return [
        DbDoctorCheck(
            "review_cases_orphan_lap",
            "error",
            _count(session, select(ReviewCaseEntity).where(
                ReviewCaseEntity.lap_record_id.is_not(None),
                ~ReviewCaseEntity.lap_record_id.in_(select(LapRecordEntity.id)),
            )),
            "Review cases linked to missing lap rows.",
        ),
        _check_sql(
            session,
            key="review_parent_mismatch",
            detail="Review run/source/result/lap links must describe one evidence chain.",
            sql="""
                SELECT COUNT(*)
                FROM review_cases rc
                LEFT JOIN extraction_results er ON er.id = rc.extraction_result_id
                LEFT JOIN lap_records l ON l.id = rc.lap_record_id
                WHERE (
                    rc.extraction_result_id IS NOT NULL
                    AND (
                        er.id IS NULL
                        OR (rc.run_id IS NOT NULL AND rc.run_id IS NOT er.run_id)
                        OR (rc.image_file_id IS NOT NULL AND rc.image_file_id IS NOT er.image_file_id)
                    )
                )
                OR (
                    rc.lap_record_id IS NOT NULL
                    AND (
                        l.id IS NULL
                        OR (rc.run_id IS NOT NULL AND rc.run_id IS NOT l.run_id)
                        OR (rc.image_file_id IS NOT NULL AND rc.image_file_id IS NOT l.image_file_id)
                        OR (
                            rc.extraction_result_id IS NOT NULL
                            AND rc.extraction_result_id IS NOT l.extraction_result_id
                        )
                    )
                )
            """,
        ),
        DbDoctorCheck(
            "flags_orphan_image",
            "error",
            _count(session, select(ImageFlagEntity).where(
                ~ImageFlagEntity.image_file_id.in_(select(ImageFileEntity.id)),
            )),
            "Image flags linked to missing image files.",
        ),
        _check_sql(
            session,
            key="flag_parent_mismatch",
            detail="Flag run/source/result/lap links must describe one evidence chain.",
            sql="""
                SELECT COUNT(*)
                FROM image_flags f
                LEFT JOIN extraction_results er ON er.id = f.extraction_result_id
                LEFT JOIN lap_records l ON l.id = f.lap_record_id
                WHERE (
                    f.extraction_result_id IS NOT NULL
                    AND (
                        er.id IS NULL
                        OR (f.run_id IS NOT NULL AND f.run_id IS NOT er.run_id)
                        OR f.image_file_id IS NOT er.image_file_id
                    )
                )
                OR (
                    f.lap_record_id IS NOT NULL
                    AND (
                        l.id IS NULL
                        OR (f.run_id IS NOT NULL AND f.run_id IS NOT l.run_id)
                        OR f.image_file_id IS NOT l.image_file_id
                        OR (
                            f.extraction_result_id IS NOT NULL
                            AND f.extraction_result_id IS NOT l.extraction_result_id
                        )
                    )
                )
            """,
        ),
        DbDoctorCheck(
            "open_flags_without_target",
            "warning",
            _count(session, select(ImageFlagEntity).where(
                ImageFlagEntity.status == "active",
                ImageFlagEntity.image_file_id.is_(None),
            )),
            "Open flags without an image target.",
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


def _keys_containing_volatile_ids(session: Session, entity_type: type, key_attr: str) -> int:
    key_column = getattr(entity_type, key_attr)
    rows = session.exec(
        select(key_column, entity_type.lap_record_id).where(entity_type.lap_record_id.is_not(None))
    ).all()
    return sum(1 for key, lap_record_id in rows if lap_record_id and lap_record_id in str(key))


def _noncanonical_review_business_keys(session: Session) -> int:
    rows = session.exec(select(ReviewCaseEntity)).all()
    return sum(1 for row in rows if row.business_key != entity_identity(row).canonical_key)
