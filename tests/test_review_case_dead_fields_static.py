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



def _class_block(source: str, class_name: str, next_class_name: str) -> str:
    start = source.index(f"class {class_name}")
    end = source.index(f"class {next_class_name}", start)
    return source[start:end]


def test_review_case_entity_no_longer_has_unused_severity_column() -> None:
    dead_field = "sever" + "ity"
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

    review_block = _class_block(models, "ReviewCaseEntity", "ReviewCorrectionEntity")
    baseline_review_table = baseline[
        baseline.index("CREATE TABLE review_cases") : baseline.index(
            "CREATE TABLE review_corrections"
        )
    ]

    assert dead_field not in review_block
    assert dead_field not in baseline_review_table
    assert '"review_cases": {"status":' in doctor
    assert dead_field not in doctor[
        doctor.index('"review_cases": {') : doctor.index('"review_corrections": {')
    ]
