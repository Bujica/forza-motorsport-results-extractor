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


def test_review_case_display_fields_are_promoted_to_columns() -> None:
    models = db_entity_source(ROOT)
    review_case_block = _class_block(models, "ReviewCaseEntity")
    reviews_repo = (
        ROOT / "forza" / "db" / "repositories" / "reviews.py"
    ).read_text(encoding="utf-8")
    baseline = (
        ROOT
        / "forza"
        / "db"
        / "migrations"
        / "versions"
        / "0001_db_vnext_schema.sql"
    ).read_text(encoding="utf-8")
    doctor = _db_doctor_source(ROOT)

    for field in (
        "source_file: str = Field(default=\"\", sa_column_kwargs={\"server_default\": text(\"''\")})",
        "weather: str = Field(default=\"unknown\", sa_column_kwargs={\"server_default\": text(\"'unknown'\")})",
        "temp_f: float | None = None",
    ):
        assert field in review_case_block

    assert "def source_file(self)" not in review_case_block
    assert "def weather(self)" not in review_case_block
    assert "def temp_f(self)" not in review_case_block

    assert "source_file=case.source_file" in reviews_repo
    assert "weather=str(case.weather)" in reviews_repo
    assert "temp_f=case.temp_f" in reviews_repo
    assert '"source_file": case.source_file' not in reviews_repo
    assert '"weather": str(case.weather)' not in reviews_repo
    assert '"temp_f": case.temp_f' not in reviews_repo

    assert "source_file VARCHAR DEFAULT '' NOT NULL" in baseline
    assert "weather VARCHAR DEFAULT 'unknown' NOT NULL" in baseline
    assert "temp_f FLOAT" in baseline

    assert '"review_cases": {' in doctor
    assert "\"source_file\": \"''\"" in doctor
    assert "\"weather\": \"'unknown'\"" in doctor


def test_lap_record_uses_race_class_without_car_class_orm_alias() -> None:
    models = db_entity_source(ROOT)
    lap_block = _class_block(models, "LapRecordEntity")

    assert "def source_file(self)" not in lap_block
    assert "race_class: str" in lap_block
    assert ("def " + "car_class(self)") not in lap_block
