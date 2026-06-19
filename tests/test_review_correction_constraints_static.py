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


def test_review_corrections_field_and_cause_constraints_are_registered() -> None:
    models = db_entity_source(ROOT)
    block = _class_block(models, "ReviewCorrectionEntity")
    baseline = (
        ROOT
        / "forza"
        / "db"
        / "migrations"
        / "versions"
        / "0001_db_vnext_schema.sql"
    ).read_text(encoding="utf-8")
    corrections_table = _create_table_block(baseline, "review_corrections")
    doctor = _db_doctor_source(ROOT)

    field_expr = "field IN ('dirty', 'track', 'weather', 'race_class', 'car', 'driver')"
    cause_expr = "cause IN ('review', 'rebuild', 'auto', 'unknown')"

    assert "ck_review_corrections_field_vocab" in block
    assert "ck_review_corrections_field_vocab" in corrections_table
    assert "ck_review_corrections_field_vocab" in doctor
    assert field_expr in block
    assert field_expr in corrections_table
    assert field_expr in doctor

    assert "ck_review_corrections_cause_vocab" in block
    assert "ck_review_corrections_cause_vocab" in corrections_table
    assert "ck_review_corrections_cause_vocab" in doctor
    assert cause_expr in block
    assert cause_expr in corrections_table
    assert cause_expr in doctor
