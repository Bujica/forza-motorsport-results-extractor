from __future__ import annotations

from sqlalchemy import text
from sqlmodel import Session

from .contracts import DbDoctorCheck


def invalid_status_values_check(session: Session) -> DbDoctorCheck:
    return _check_sql(
        session,
        key="invalid_status_values",
        detail="Persisted lifecycle/status fields must use the DB vNext vocabulary.",
        sql="""
            SELECT
                (SELECT COUNT(*) FROM extraction_runs
                 WHERE status NOT IN ('pending', 'running', 'completed', 'failed', 'cancelled'))
              + (SELECT COUNT(*) FROM extraction_results
                 WHERE status NOT IN ('pending', 'running', 'ok', 'error', 'cancelled'))
              + (SELECT COUNT(*) FROM extraction_attempts
                 WHERE status NOT IN ('ok', 'error', 'cancelled'))
              + (SELECT COUNT(*) FROM image_files
                 WHERE file_status NOT IN ('available', 'missing')
                    OR best_lap_status NOT IN (
                        'pending', 'contributing', 'non_contributing'
                    ))
              + (SELECT COUNT(*) FROM review_cases
                 WHERE status NOT IN ('open', 'resolved', 'ignored', 'auto_resolved')
                    OR reason NOT IN ('dirty_lap', 'track', 'weather', 'race_class', 'car', 'driver_name')
                    OR outcome NOT IN ('pending', 'confirmed', 'model_error', 'ignored')
                    OR ("trigger" IS NOT NULL AND "trigger" NOT IN ('model_marked_dirty', 'weather_unknown', 'rain_time_suspicious', 'track_unknown', 'track_unresolved', 'track_not_in_reference', 'class_unknown', 'class_invalid', 'car_empty', 'car_not_in_reference', 'driver_name_empty', 'numeric_prefix', 'invalid_symbol'))
                    OR (decision_field IS NOT NULL AND decision_field NOT IN ('dirty', 'track', 'weather', 'race_class', 'car', 'driver')))
              + (SELECT COUNT(*) FROM image_flags
                 WHERE status NOT IN ('active', 'resolved', 'ignored')
                    OR flag_scope NOT IN ('image', 'lap')
                    OR flag_type NOT IN ('duplicate', 'dirty_lap', 'track', 'weather', 'race_class', 'car', 'driver_name'))
        """,
    )


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
) -> DbDoctorCheck:
    return DbDoctorCheck(key, severity, _scalar_sql(session, sql), detail)
