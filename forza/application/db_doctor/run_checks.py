from __future__ import annotations

from sqlalchemy import text
from sqlmodel import Session

from .contracts import DbDoctorCheck


def run_counter_checks(session: Session) -> list[DbDoctorCheck]:
    return [
        _check_sql(
            session,
            key="runs_left_running",
            detail="No run may remain running after the owning process exits.",
            sql="SELECT COUNT(*) FROM extraction_runs WHERE status = 'running'",
        ),
        _check_sql(
            session,
            key="run_counters_mismatch",
            detail="Run input/result/review counters must match relational rows.",
            sql="""
                SELECT COUNT(*)
                FROM extraction_runs r
                WHERE r.total_inputs <> (
                    SELECT COUNT(*) FROM run_inputs ri WHERE ri.run_id = r.id
                )
                   OR r.to_process <> (
                    SELECT COUNT(*) FROM run_inputs ri
                    WHERE ri.run_id = r.id AND ri.decision = 'process'
                )
                   OR r.skipped <> (
                    SELECT COUNT(*) FROM run_inputs ri
                    WHERE ri.run_id = r.id
                      AND ri.decision NOT IN ('process', 'duplicate')
                )
                   OR r.duplicate_count <> (
                    SELECT COUNT(*) FROM run_inputs ri
                    WHERE ri.run_id = r.id AND ri.decision = 'duplicate'
                )
                   OR r.processed <> (
                    SELECT COUNT(*) FROM extraction_results er WHERE er.run_id = r.id
                )
                   OR r.succeeded <> (
                    SELECT COUNT(*) FROM extraction_results er
                    WHERE er.run_id = r.id AND er.status = 'ok'
                )
                   OR r.failed <> (
                    SELECT COUNT(*) FROM extraction_results er
                    WHERE er.run_id = r.id AND er.status = 'error'
                )
                   OR r.review_case_count <> (
                    SELECT COUNT(*) FROM review_cases rc
                    WHERE rc.run_id = r.id AND rc.status = 'open'
                )
            """,
        ),
    ]


def run_input_contract_checks(session: Session) -> list[DbDoctorCheck]:
    return [
        _check_sql(
            session,
            key="run_input_contract_invalid",
            detail="run_inputs decisions and reason fields must not be overloaded.",
            sql="""
                SELECT COUNT(*)
                FROM run_inputs
                WHERE decision NOT IN (
                    'process', 'skip', 'duplicate', 'missing',
                    'unsupported', 'outside_input', 'hash_failed'
                )
                   OR (decision <> 'process' AND process_reason IS NOT NULL)
                   OR (decision = 'process' AND (skip_reason IS NOT NULL OR duplicate_kind IS NOT NULL))
                   OR (decision = 'duplicate' AND duplicate_kind IS NULL)
                   OR (decision <> 'duplicate' AND duplicate_kind IS NOT NULL)
                   OR (duplicate_kind IS NOT NULL AND duplicate_kind NOT IN ('hash', 'batch'))
            """,
        ),
        _check_sql(
            session,
            key="run_input_duplicate_link_invalid",
            detail="Duplicate inputs must retain valid same-run canonical hash/link evidence.",
            sql="""
                SELECT COUNT(*)
                FROM run_inputs d
                LEFT JOIN run_inputs p ON p.id = d.duplicate_of_input_id
                WHERE (
                    d.decision = 'duplicate'
                    AND (
                        d.file_hash IS NULL
                        OR d.duplicate_of_hash IS NULL
                        OR d.file_hash <> d.duplicate_of_hash
                        OR (d.duplicate_kind = 'batch' AND d.duplicate_of_input_id IS NULL)
                        OR (
                            d.duplicate_of_input_id IS NOT NULL
                            AND (
                                p.id IS NULL
                                OR p.run_id <> d.run_id
                                OR p.input_order >= d.input_order
                                OR p.file_hash <> d.duplicate_of_hash
                            )
                        )
                    )
                )
                OR (
                    d.decision <> 'duplicate'
                    AND (
                        d.duplicate_of_hash IS NOT NULL
                        OR d.duplicate_of_input_id IS NOT NULL
                    )
                )
            """,
        ),
        _check_sql(
            session,
            key="final_runs_with_nonfinal_results",
            detail="Completed, failed, or cancelled runs cannot retain pending/running results.",
            sql="""
                SELECT COUNT(*)
                FROM extraction_results er
                JOIN extraction_runs r ON r.id = er.run_id
                WHERE r.status IN ('completed', 'failed', 'cancelled')
                  AND er.status IN ('pending', 'running')
            """,
        ),
    ]


def run_input_process_checks(session: Session) -> list[DbDoctorCheck]:
    return [
        DbDoctorCheck(
            "preflight_failure_created_results",
            "error",
            _scalar_sql(
                session,
                """
                SELECT COUNT(*)
                FROM extraction_runs r
                WHERE r.operational_error_code = 'lmstudio_preflight_failed'
                  AND EXISTS (
                      SELECT 1
                      FROM extraction_results er
                      WHERE er.run_id = r.id
                  )
                """,
            ),
            "Run-level operational/preflight failures must not create extraction results.",
        ),
        _check_sql(
            session,
            key="run_inputs_process_without_image_file",
            detail="run_inputs with decision=process must have image_file_id.",
            sql="""
                SELECT COUNT(*)
                FROM run_inputs
                WHERE decision = 'process'
                  AND image_file_id IS NULL
            """,
        ),
        _check_sql(
            session,
            key="run_inputs_process_without_one_result",
            detail="run_inputs with decision=process must have exactly one extraction_result.",
            sql="""
                SELECT COUNT(*)
                FROM run_inputs ri
                LEFT JOIN extraction_results er ON er.run_input_id = ri.id
                WHERE ri.decision = 'process'
                GROUP BY ri.id
                HAVING COUNT(er.id) <> 1
            """,
            count_groups=True,
        ),
    ]


def result_input_parent_mismatch_check(session: Session) -> DbDoctorCheck:
    return _check_sql(
        session,
        key="result_input_parent_mismatch",
        detail="Extraction result run/source links must match its run_input.",
        sql="""
            SELECT COUNT(*)
            FROM extraction_results er
            JOIN run_inputs ri ON ri.id = er.run_input_id
            WHERE er.run_id IS NOT ri.run_id
               OR er.image_file_id IS NOT ri.image_file_id
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
    count_groups: bool = False,
) -> DbDoctorCheck:
    if count_groups:
        rows = session.exec(text(sql)).all()
        count = len(rows)
    else:
        count = _scalar_sql(session, sql)
    return DbDoctorCheck(key, severity, count, detail)
