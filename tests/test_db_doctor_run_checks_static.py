from __future__ import annotations

from pathlib import Path

from forza.application import db_doctor_service
from forza.application.db_doctor import run_checks
from forza.application.db_doctor.contracts import DbDoctorCheck
from forza.application.db_doctor.run_checks import (
    result_input_parent_mismatch_check,
    run_counter_checks,
    run_input_contract_checks,
    run_input_process_checks,
)


ROOT = Path(__file__).resolve().parents[1]


def test_run_checks_move_out_of_service_surface() -> None:
    service_source = (ROOT / "forza" / "application" / "db_doctor_service.py").read_text(encoding="utf-8")
    run_checks_source = (ROOT / "forza" / "application" / "db_doctor" / "run_checks.py").read_text(encoding="utf-8")
    artifact_checks_source = (ROOT / "forza" / "application" / "db_doctor" / "artifact_checks.py").read_text(encoding="utf-8")

    assert "*run_counter_checks(session)" in service_source
    assert "*run_input_contract_checks(session)" in service_source
    assert "*run_input_process_checks(session)" in service_source
    assert "result_input_parent_mismatch_check(session)" in artifact_checks_source

    moved_keys = (
        "runs_left_running",
        "run_counters_mismatch",
        "run_input_contract_invalid",
        "run_input_duplicate_link_invalid",
        "final_runs_with_nonfinal_results",
        "preflight_failure_created_results",
        "run_inputs_process_without_image_file",
        "run_inputs_process_without_one_result",
        "result_input_parent_mismatch",
    )
    for key in moved_keys:
        assert f'"{key}"' not in service_source
        assert f"'{key}'" not in service_source
        assert key in run_checks_source


def test_run_check_functions_preserve_key_order(monkeypatch) -> None:
    def fake_check_sql(_session, *, key, detail, sql, severity="error", count_groups=False):
        return DbDoctorCheck(key, severity, 0, detail)

    monkeypatch.setattr(run_checks, "_check_sql", fake_check_sql)
    monkeypatch.setattr(run_checks, "_scalar_sql", lambda _session, _sql: 0)

    assert [check.key for check in run_counter_checks(object())] == [
        "runs_left_running",
        "run_counters_mismatch",
    ]
    assert [check.key for check in run_input_contract_checks(object())] == [
        "run_input_contract_invalid",
        "run_input_duplicate_link_invalid",
        "final_runs_with_nonfinal_results",
    ]
    assert [check.key for check in run_input_process_checks(object())] == [
        "preflight_failure_created_results",
        "run_inputs_process_without_image_file",
        "run_inputs_process_without_one_result",
    ]
    assert result_input_parent_mismatch_check(object()).key == "result_input_parent_mismatch"


def test_db_doctor_service_compatibility_exports_run_check_helpers() -> None:
    assert db_doctor_service.run_counter_checks is run_counter_checks
    assert db_doctor_service.run_input_contract_checks is run_input_contract_checks
    assert db_doctor_service.run_input_process_checks is run_input_process_checks
    assert db_doctor_service.result_input_parent_mismatch_check is result_input_parent_mismatch_check
