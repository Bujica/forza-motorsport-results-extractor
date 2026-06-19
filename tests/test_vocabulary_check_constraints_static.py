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


EXPECTED_CONSTRAINTS = (
    "ck_image_files_file_status_vocab",
    "ck_image_files_best_lap_status_vocab",
    "ck_extraction_runs_status_vocab",
    "ck_extraction_runs_mode_vocab",
    "ck_run_inputs_decision_vocab",
    "ck_run_inputs_duplicate_kind_vocab",
    "ck_extraction_results_status_vocab",
    "ck_extraction_attempts_status_vocab",
    "ck_review_cases_status_vocab",
    "ck_review_cases_outcome_vocab",
    "ck_review_cases_reason_vocab",
    "ck_review_cases_trigger_vocab",
    "ck_review_cases_decision_field_vocab",
    "ck_review_corrections_field_vocab",
    "ck_review_corrections_cause_vocab",
    "ck_external_record_imports_status_vocab",
    "ck_external_lap_records_weather_vocab",
    "ck_image_flags_status_vocab",
    "ck_image_flags_scope_vocab",
    "ck_image_flags_flag_type_vocab",
)


def _constraint_line(source: str, name: str) -> str:
    for line in source.splitlines():
        if name in line:
            return line
    raise AssertionError(f"Missing constraint: {name}")


def test_vocabulary_check_constraints_are_modelled_baselined_and_audited() -> None:
    models = db_entity_source(ROOT)
    baseline = (
        ROOT
        / "forza"
        / "db"
        / "migrations"
        / "versions"
        / "0001_db_vnext_schema.sql"
    ).read_text(encoding="utf-8")
    doctor = _db_doctor_source(ROOT)

    assert "_EXPECTED_SCHEMA_MIGRATION_REVISIONS = ()" in doctor
    assert "vocabulary_check_constraints_missing" in doctor

    for name in EXPECTED_CONSTRAINTS:
        assert name in models
        assert name in baseline
        assert name in doctor


def test_post_squash_vocabulary_migrations_are_removed() -> None:
    versions = ROOT / "forza" / "db" / "migrations" / "versions"

    for revision in (
        "0005_vocabulary_check_constraints.py",
        "0006_widen_review_reason_vocabulary.py",
        "0007_widen_review_reason_trigger_vocabulary.py",
    ):
        assert not (versions / revision).exists()


def test_review_case_reason_vocabulary_is_canonical_only() -> None:
    models = db_entity_source(ROOT)
    baseline = (
        ROOT
        / "forza"
        / "db"
        / "migrations"
        / "versions"
        / "0001_db_vnext_schema.sql"
    ).read_text(encoding="utf-8")

    reason_model = _constraint_line(models, "ck_review_cases_reason_vocab")
    reason_sql = _constraint_line(baseline, "ck_review_cases_reason_vocab")

    for value in (
        "dirty_lap",
        "track",
        "weather",
        "race_class",
        "car",
        "driver_name",
    ):
        assert value in reason_model
        assert value in reason_sql

    for removed_reason in ("gamertag", "driver_name_invalid"):
        assert removed_reason not in reason_model
        assert removed_reason not in reason_sql

    for non_reason in (
        "track_uncertain",
        "class_uncertain",
        "model_marked_dirty",
        "weather_unknown",
        "track_unknown",
        "track_unresolved",
        "class_unknown",
        "car_empty",
        "driver_name_empty",
        "numeric_prefix",
        "invalid_symbol",
    ):
        assert non_reason not in reason_model
        assert non_reason not in reason_sql


def test_image_flag_vocabulary_covers_review_reasons_and_image_flags() -> None:
    models = db_entity_source(ROOT)
    baseline = (
        ROOT
        / "forza"
        / "db"
        / "migrations"
        / "versions"
        / "0001_db_vnext_schema.sql"
    ).read_text(encoding="utf-8")
    doctor = _db_doctor_source(ROOT)

    model_line = _constraint_line(models, "ck_image_flags_flag_type_vocab")
    baseline_line = _constraint_line(baseline, "ck_image_flags_flag_type_vocab")
    doctor_line = _constraint_line(doctor, "ck_image_flags_flag_type_vocab")

    for value in (
        "duplicate",
        "dirty_lap",
        "track",
        "weather",
        "race_class",
        "car",
        "driver_name",
    ):
        assert value in model_line
        assert value in baseline_line
        assert value in doctor_line

    for removed_flag_type in (
        "gamertag",
        "driver_name_invalid",
        "track_uncertain",
        "class_uncertain",
    ):
        assert removed_flag_type not in model_line
        assert removed_flag_type not in baseline_line
        assert removed_flag_type not in doctor_line


def test_review_case_trigger_vocabulary_keeps_review_triggers_only() -> None:
    models = db_entity_source(ROOT)
    baseline = (
        ROOT
        / "forza"
        / "db"
        / "migrations"
        / "versions"
        / "0001_db_vnext_schema.sql"
    ).read_text(encoding="utf-8")

    trigger_model = _constraint_line(models, "ck_review_cases_trigger_vocab")
    trigger_sql = _constraint_line(baseline, "ck_review_cases_trigger_vocab")

    for value in (
        "model_marked_dirty",
        "weather_unknown",
        "rain_time_suspicious",
        "track_unknown",
        "track_unresolved",
        "track_not_in_reference",
        "class_unknown",
        "class_invalid",
        "car_empty",
        "car_not_in_reference",
        "driver_name_empty",
        "numeric_prefix",
        "invalid_symbol",
    ):
        assert value in trigger_model
        assert value in trigger_sql

    for non_trigger in ("track_uncertain", "class_uncertain", "driver_name_invalid"):
        assert non_trigger not in trigger_model
        assert non_trigger not in trigger_sql


def test_review_case_decision_field_vocabulary_matches_gui_write_fields() -> None:
    models = db_entity_source(ROOT)
    baseline = (
        ROOT
        / "forza"
        / "db"
        / "migrations"
        / "versions"
        / "0001_db_vnext_schema.sql"
    ).read_text(encoding="utf-8")

    decision_model = _constraint_line(models, "ck_review_cases_decision_field_vocab")
    decision_sql = _constraint_line(baseline, "ck_review_cases_decision_field_vocab")

    for value in ("dirty", "track", "weather", "race_class", "car", "driver"):
        assert value in decision_model
        assert value in decision_sql

    assert "gamertag" not in decision_model
    assert "gamertag" not in decision_sql
    assert "legacy_endpoint_field" not in decision_model
    assert "legacy_endpoint_field" not in decision_sql


def test_review_correction_vocabulary_constraints_match_repository_fields() -> None:
    models = db_entity_source(ROOT)
    baseline = (
        ROOT
        / "forza"
        / "db"
        / "migrations"
        / "versions"
        / "0001_db_vnext_schema.sql"
    ).read_text(encoding="utf-8")

    field_model = _constraint_line(models, "ck_review_corrections_field_vocab")
    field_sql = _constraint_line(baseline, "ck_review_corrections_field_vocab")
    cause_model = _constraint_line(models, "ck_review_corrections_cause_vocab")
    cause_sql = _constraint_line(baseline, "ck_review_corrections_cause_vocab")

    for value in ("dirty", "track", "weather", "race_class", "car", "driver"):
        assert value in field_model
        assert value in field_sql

    for value in ("review", "rebuild", "auto", "unknown"):
        assert value in cause_model
        assert value in cause_sql

    assert "gamertag" not in field_model
    assert "legacy_field" not in field_model
    assert "legacy_cause" not in cause_model
