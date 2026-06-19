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


def test_lap_record_source_file_is_promoted_to_column() -> None:
    models = db_entity_source(ROOT)
    lap_block = _class_block(models, "LapRecordEntity")
    laps_repo = (ROOT / "forza" / "db" / "repositories" / "laps.py").read_text(
        encoding="utf-8"
    )
    baseline = (
        ROOT
        / "forza"
        / "db"
        / "migrations"
        / "versions"
        / "0001_db_vnext_schema.sql"
    ).read_text(encoding="utf-8")
    doctor = _db_doctor_source(ROOT)

    assert "source_file: str = Field(default=\"\", sa_column_kwargs={\"server_default\": text(\"''\")})" in lap_block
    assert "def source_file(self)" not in lap_block
    assert "@source_file.setter" not in lap_block
    assert "raw_lap_json" in lap_block
    assert ("def " + "car_class(self)") not in lap_block
    assert ("def " + "track_suggestions(self)") not in lap_block

    assert "source_file=result.source_file" in laps_repo
    assert '"source_file": result.source_file' not in laps_repo

    assert "source_file VARCHAR DEFAULT '' NOT NULL" in baseline
    assert '"lap_records": {' in doctor
    assert "\"source_file\": \"''\"" in doctor


def test_review_case_display_field_columns_remain_separate() -> None:
    models = db_entity_source(ROOT)
    review_block = _class_block(models, "ReviewCaseEntity")

    assert "source_file: str = Field(default=\"\", sa_column_kwargs={\"server_default\": text(\"''\")})" in review_block
    assert "weather: str = Field(default=\"unknown\"" in review_block
    assert "temp_f: float | None = None" in review_block
