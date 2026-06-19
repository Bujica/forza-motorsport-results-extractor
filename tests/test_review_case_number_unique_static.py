from __future__ import annotations

from pathlib import Path

from tests._db_entity_source import db_entity_source

ROOT = Path(__file__).resolve().parents[1]


def _class_block(source: str, class_name: str) -> str:
    start = source.index(f"class {class_name}")
    next_class = source.find("\nclass ", start + 1)
    return source[start:] if next_class == -1 else source[start:next_class]


def _create_table_block(sql: str, table_name: str) -> str:
    start = sql.index(f"CREATE TABLE {table_name}")
    end = sql.index(");", start)
    return sql[start:end]


def test_review_case_number_is_globally_unique_in_model_and_baseline() -> None:
    models = db_entity_source(ROOT)
    review_model = _class_block(models, "ReviewCaseEntity")
    baseline = (
        ROOT
        / "forza"
        / "db"
        / "migrations"
        / "versions"
        / "0001_db_vnext_schema.sql"
    ).read_text(encoding="utf-8")
    review_table = _create_table_block(baseline, "review_cases")

    assert 'UniqueConstraint("case_number", name="uq_review_cases_case_number")' in review_model
    assert "CONSTRAINT uq_review_cases_case_number UNIQUE (case_number)" in review_table
