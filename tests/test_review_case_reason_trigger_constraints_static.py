from __future__ import annotations

from pathlib import Path

from tests._db_entity_source import db_entity_source

ROOT = Path(__file__).resolve().parents[1]


def _db_doctor_source(root: Path) -> str:
    return "\n".join(
        (
            (root / "forza" / "application" / "db_doctor_service.py").read_text(
                encoding="utf-8"
            ),
            (root / "forza" / "application" / "db_doctor" / "status_checks.py").read_text(
                encoding="utf-8"
            ),
            (root / "forza" / "application" / "db_doctor" / "schema_checks.py").read_text(
                encoding="utf-8"
            ),
        )
    )


def _class_block(source: str, class_name: str) -> str:
    start = source.index(f"class {class_name}")
    next_class = source.find("\nclass ", start + 1)
    return source[start:] if next_class == -1 else source[start:next_class]


def _create_table_block(sql: str, table_name: str) -> str:
    start = sql.index(f"CREATE TABLE {table_name}")
    end = sql.index(");", start)
    return sql[start:end]


def _constraint_line(source: str, name: str) -> str:
    for line in source.splitlines():
        if name in line:
            return line
    raise AssertionError(f"Missing constraint: {name}")


def test_review_reason_trigger_and_decision_field_vocabularies_are_separate() -> None:
    models = db_entity_source(ROOT)
    block = _class_block(models, "ReviewCaseEntity")
    baseline = (
        ROOT
        / "forza"
        / "db"
        / "migrations"
        / "versions"
        / "0001_db_vnext_schema.sql"
    ).read_text(encoding="utf-8")
    review_table = _create_table_block(baseline, "review_cases")
    doctor = _db_doctor_source(ROOT)
    gui_write_tests = "\n".join(
        (ROOT / "tests" / path).read_text(encoding="utf-8")
        for path in (
            "test_gui_write_image_status.py",
            "test_gui_write_flags_cases.py",
            "test_gui_write_dirty_decisions.py",
            "test_gui_write_field_decisions.py",
        )
    )

    reason_expr = "reason IN ('dirty_lap', 'track', 'weather', 'race_class', 'car', 'driver_name')"
    trigger_sql_expr = "\"trigger\" IS NULL OR \"trigger\" IN ('model_marked_dirty', 'weather_unknown', 'rain_time_suspicious', 'track_unknown', 'track_unresolved', 'track_not_in_reference', 'class_unknown', 'class_invalid', 'car_empty', 'car_not_in_reference', 'driver_name_empty', 'numeric_prefix', 'invalid_symbol')"
    trigger_source_expr = "\\\"trigger\\\" IS NULL OR \\\"trigger\\\" IN ('model_marked_dirty', 'weather_unknown', 'rain_time_suspicious', 'track_unknown', 'track_unresolved', 'track_not_in_reference', 'class_unknown', 'class_invalid', 'car_empty', 'car_not_in_reference', 'driver_name_empty', 'numeric_prefix', 'invalid_symbol')"
    decision_expr = "decision_field IS NULL OR decision_field IN ('dirty', 'track', 'weather', 'race_class', 'car', 'driver')"

    reason_line = _constraint_line(block, "ck_review_cases_reason_vocab")
    assert reason_expr in reason_line
    assert "weather_unknown" not in reason_line
    assert "track_uncertain" not in reason_line
    assert "gamertag" not in reason_line
    assert "driver_name_invalid" not in reason_line
    assert reason_expr in review_table

    assert "ck_review_cases_trigger_vocab" in block
    assert "ck_review_cases_trigger_vocab" in review_table
    assert trigger_source_expr in block
    assert trigger_sql_expr in review_table
    assert "gamertag_empty" not in block
    assert "gamertag_empty" not in review_table

    assert "ck_review_cases_decision_field_vocab" in block
    assert "ck_review_cases_decision_field_vocab" in review_table
    assert decision_expr in block
    assert decision_expr in review_table
    assert "decision_field IS NULL OR decision_field IN ('dirty', 'track', 'weather', 'race_class', 'car', 'driver', 'gamertag')" not in block

    assert "ck_review_cases_trigger_vocab" in doctor
    assert "ck_review_cases_decision_field_vocab" in doctor
    assert decision_expr in doctor
    assert "decision_field IS NOT NULL AND decision_field NOT IN ('dirty', 'track', 'weather', 'race_class', 'car', 'driver')" in doctor

    assert 'case.reason = "track_unresolved"' not in gui_write_tests
    assert 'case.reason = "weather_unknown"' not in gui_write_tests
    assert 'reason="track_uncertain"' not in gui_write_tests


def test_removed_lab_seed_tests_are_absent() -> None:
    removed = ROOT / "tests" / ("test_" + "developer_lab_service.py")

    assert not removed.exists()
