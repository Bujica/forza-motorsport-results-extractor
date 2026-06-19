from __future__ import annotations

from pathlib import Path

from sqlmodel import Session

from .db_doctor.contracts import DbDoctorCheck, DbDoctorReport
from .db_doctor.sqlite_checks import (
    foreign_key_violations_check,
    schema_head_check,
    sqlite_integrity_check,
)
from .db_doctor.run_checks import (
    result_input_parent_mismatch_check,
    run_counter_checks,
    run_input_contract_checks,
    run_input_process_checks,
)
from .db_doctor.status_checks import invalid_status_values_check
from .db_doctor.image_file_checks import (
    best_lap_status_checks,
    best_lap_value_checks,
    lap_parent_checks,
    image_file_checks,
)
from .db_doctor.review_checks import (
    review_core_checks,
    review_model_error_identity_checks,
    review_parent_flag_checks,
)
from .db_doctor.artifact_checks import result_artifact_checks
from .db_doctor.schema_checks import schema_drift_checks
from ..db import create_sqlite_engine
from ..db.migrate import detect_database_state


class DbDoctorService:
    def run(self, database_file: Path) -> DbDoctorReport:
        database_file = Path(database_file)
        schema_state = detect_database_state(database_file).value
        schema_check = schema_head_check(schema_state)
        if schema_check is not None:
            return DbDoctorReport(
                database_file=database_file,
                schema_state=schema_state,
                checks=[schema_check],
            )
        engine = create_sqlite_engine(database_file, apply_runtime_pragmas=False)
        try:
            with Session(engine) as session:
                checks = [
                    sqlite_integrity_check(session),
                    foreign_key_violations_check(session),
                    *run_counter_checks(session),
                    invalid_status_values_check(session),
                    *run_input_contract_checks(session),
                    *image_file_checks(session),
                    *run_input_process_checks(session),
                    *result_artifact_checks(session),
                    *review_core_checks(session),
                    *best_lap_value_checks(session),
                    *review_model_error_identity_checks(session),
                    *lap_parent_checks(session),
                    *review_parent_flag_checks(session),
                    *best_lap_status_checks(session),
                    *schema_drift_checks(session),
                ]
        finally:
            engine.dispose()
        return DbDoctorReport(database_file=database_file, schema_state=schema_state, checks=checks)

