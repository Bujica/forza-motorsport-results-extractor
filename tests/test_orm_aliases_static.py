from __future__ import annotations

from pathlib import Path

from tests._db_entity_source import db_entity_source


ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "forza" / "db" / "models.py"


def _class_block(source: str, class_name: str, next_class_name: str) -> str:
    start = source.index(f"class {class_name}")
    end = source.index(f"class {next_class_name}", start)
    return source[start:end]


def test_image_flag_entity_uses_flag_type_without_orm_flag_alias() -> None:
    source = db_entity_source(ROOT)
    block = _class_block(source, "ImageFlagEntity", "ExportArtifactEntity")

    assert "flag_type: str" in block
    assert ("def " + "flag(self)") not in block
    assert ("@" + "flag.setter") not in block

def test_review_case_entity_uses_track_suggestions_json_without_orm_alias() -> None:
    source = db_entity_source(ROOT)
    block = _class_block(source, "ReviewCaseEntity", "ReviewCorrectionEntity")

    assert "track_suggestions_json" in block
    assert ("def " + "track_suggestions(self)") not in block
    assert ("@" + "track_suggestions.setter") not in block

def test_lap_record_entity_uses_race_class_without_orm_car_class_alias() -> None:
    source = db_entity_source(ROOT)
    block = _class_block(source, "LapRecordEntity", "ReviewCaseEntity")

    assert "race_class: str" in block
    assert ("def " + "car_class(self)") not in block
    assert ("@" + "car_class.setter") not in block

def test_extraction_run_entity_uses_config_extra_json_without_orm_config_alias() -> None:
    source = db_entity_source(ROOT)
    block = _class_block(source, "ExtractionRunEntity", "RunInputEntity")

    assert "config_extra_json: str | None = None" in block
    assert ("def " + "config(self)") not in block
    assert ("@" + "config.setter") not in block

def test_legacy_model_alias_properties_stay_removed() -> None:
    source = db_entity_source(ROOT)

    forbidden = (
        "def file_size_bytes(self",
        "def file_modified_at(self",
        "def duplicate_of_image_file_id(self",
        "def prompt_name(self",
        "def error_message(self",
        "def reasoning_output_tokens(self",
        "def time_to_first_token_seconds(self",
        "def model_load_time_seconds(self",
        "def request_image_width_px(self",
        "def request_image_height_px(self",
        "def format(self",
        "def path(self",
        "def total_rows(self",
        "def accepted_rows(self",
        "def rejected_rows(self",
        "def issue_count(self",
        "def source(self",
        "def imported_at(self",
    )
    for token in forbidden:
        assert token not in source

