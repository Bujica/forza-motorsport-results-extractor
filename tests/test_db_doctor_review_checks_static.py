from __future__ import annotations

import importlib
import re
from pathlib import Path

from forza.application import db_doctor_service
from forza.application.db_doctor.contracts import DbDoctorCheck
from forza.application.db_doctor.review_checks import (
    review_core_checks,
    review_model_error_identity_checks,
    review_parent_flag_checks,
)


ROOT = Path(__file__).resolve().parents[1]
MODULE = importlib.import_module("forza.application.db_doctor.review_checks")


def test_review_checks_move_out_of_service_surface() -> None:
    service_source = (ROOT / "forza" / "application" / "db_doctor_service.py").read_text(encoding="utf-8")
    module_source = (ROOT / "forza" / "application" / "db_doctor" / "review_checks.py").read_text(encoding="utf-8")

    assert "*review_core_checks(session)" in service_source
    assert "*review_model_error_identity_checks(session)" in service_source
    assert "*review_parent_flag_checks(session)" in service_source

    moved_keys = (
        "open_reviews_missing_active_flag",
        "stale_active_review_flags",
        "review_cases_invalid_reason",
        "review_corrections_invalid",
        "model_error_missing_decision",
        "model_error_missing_raw_evidence",
        "review_business_key_uses_lap_record_id",
        "review_business_key_not_canonical",
        "review_corrections_orphan_source",
        "flag_key_uses_lap_record_id",
        "review_cases_orphan_lap",
        "review_parent_mismatch",
        "flags_orphan_image",
        "flag_parent_mismatch",
        "open_flags_without_target",
    )
    for key in moved_keys:
        assert f'"{key}"' not in service_source
        assert f"'{key}'" not in service_source
        assert key in module_source

    assert "def _keys_containing_volatile_ids" not in service_source
    assert "def _noncanonical_review_business_keys" not in service_source
    assert "from ..db.review_identity import" not in service_source


def test_review_check_functions_preserve_key_order(monkeypatch) -> None:
    def fake_check_sql(_session, *, key, detail, sql, severity="error", count_groups=False):
        return DbDoctorCheck(key, severity, 0, detail)

    monkeypatch.setattr(MODULE, "_check_sql", fake_check_sql)
    monkeypatch.setattr(MODULE, "_count", lambda _session, _query: 3)
    monkeypatch.setattr(MODULE, "_keys_containing_volatile_ids", lambda _session, _entity_type, _key_attr: 4)
    monkeypatch.setattr(MODULE, "_noncanonical_review_business_keys", lambda _session: 5)

    assert [check.key for check in review_core_checks(object())] == [
        "open_reviews_missing_active_flag",
        "stale_active_review_flags",
        "review_cases_invalid_reason",
        "review_corrections_invalid",
    ]
    assert [check.key for check in review_model_error_identity_checks(object())] == [
        "model_error_missing_decision",
        "model_error_missing_raw_evidence",
        "review_business_key_uses_lap_record_id",
        "review_business_key_not_canonical",
        "review_corrections_orphan_source",
        "flag_key_uses_lap_record_id",
    ]
    assert [check.key for check in review_parent_flag_checks(object())] == [
        "review_cases_orphan_lap",
        "review_parent_mismatch",
        "flags_orphan_image",
        "flag_parent_mismatch",
        "open_flags_without_target",
    ]


def test_review_invalid_reason_check_matches_reason_constraint() -> None:
    module_source = (ROOT / "forza" / "application" / "db_doctor" / "review_checks.py").read_text(encoding="utf-8")
    review_entity = (ROOT / "forza" / "db" / "entities" / "review.py").read_text(encoding="utf-8")

    expected = _quoted_values(_line_containing(review_entity, "ck_review_cases_reason_vocab"))
    doctor_block = _block_containing(module_source, 'key="review_cases_invalid_reason"')

    assert _quoted_values(doctor_block) == expected


def test_db_doctor_service_compatibility_exports_review_check_helpers() -> None:
    assert db_doctor_service.review_core_checks is review_core_checks
    assert db_doctor_service.review_model_error_identity_checks is review_model_error_identity_checks
    assert db_doctor_service.review_parent_flag_checks is review_parent_flag_checks


def _line_containing(source: str, token: str) -> str:
    for line in source.splitlines():
        if token in line:
            return line
    raise AssertionError(f"Missing token: {token}")


def _block_containing(source: str, token: str) -> str:
    start = source.index(token)
    end = source.index("_check_sql(", start + 1)
    return source[start:end]


def _quoted_values(source: str) -> list[str]:
    return re.findall(r"'([^']+)'", source)
