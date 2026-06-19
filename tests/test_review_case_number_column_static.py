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



def _has_create_table(sql: str, table: str) -> bool:
    return f"CREATE TABLE {table}" in sql or f'CREATE TABLE "{table}"' in sql


def test_review_case_number_is_promoted_to_column() -> None:
    models = db_entity_source(ROOT)
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

    assert "case_number: int = Field(" in models
    assert "def case_number(self)" not in models
    legacy_payload = "details" + "_json"
    assert f"func.json_extract(ReviewCaseEntity.{legacy_payload}" not in reviews_repo
    assert "func.max(ReviewCaseEntity.case_number)" in reviews_repo
    assert "case_number=case.case_number" in reviews_repo
    assert '"case_number": case.case_number' not in reviews_repo

    assert "case_number INTEGER DEFAULT 0 NOT NULL" in baseline
    assert "_EXPECTED_SCHEMA_MIGRATION_REVISIONS = ()" in doctor


def test_review_case_number_column_is_squashed_into_baseline() -> None:
    versions = ROOT / "forza" / "db" / "migrations" / "versions"
    assert not (versions / "0008_review_case_number_column.py").exists()

    baseline = (versions / "0001_db_vnext_schema.sql").read_text(encoding="utf-8")
    assert _has_create_table(baseline, "review_cases")
    assert "case_number INTEGER DEFAULT 0 NOT NULL" in baseline


def test_review_case_number_column_has_no_json_property_shadow() -> None:
    models = db_entity_source(ROOT)

    assert "@case_number.setter" not in models
    assert "def case_number(self)" not in models
    assert "case_number: int = Field(default=0" in models
