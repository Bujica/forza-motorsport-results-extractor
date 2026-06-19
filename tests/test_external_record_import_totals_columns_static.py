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


def test_external_record_import_totals_are_promoted_to_columns() -> None:
    models = db_entity_source(ROOT)
    block = _class_block(models, "ExternalRecordImportEntity")
    repo = (
        ROOT / "forza" / "db" / "repositories" / "external_records.py"
    ).read_text(encoding="utf-8")
    doctor = _db_doctor_source(ROOT)
    baseline = (
        ROOT
        / "forza"
        / "db"
        / "migrations"
        / "versions"
        / "0001_db_vnext_schema.sql"
    ).read_text(encoding="utf-8")
    import_block = _create_table_block(baseline, "external_record_imports")

    assert "totals:" not in block
    assert "totals JSON" not in import_block
    assert "totals={" not in repo

    for field in (
        "total_rows: int = Field(default=0",
        "accepted_rows: int = Field(default=0",
        "rejected_rows: int = Field(default=0",
        "issue_count: int = Field(default=0",
    ):
        assert field in block

    for column in (
        "total_rows INTEGER DEFAULT 0 NOT NULL",
        "accepted_rows INTEGER DEFAULT 0 NOT NULL",
        "rejected_rows INTEGER DEFAULT 0 NOT NULL",
        "issue_count INTEGER DEFAULT 0 NOT NULL",
    ):
        assert column in import_block

    for constraint in (
        "ck_external_record_imports_total_rows",
        "ck_external_record_imports_accepted_rows",
        "ck_external_record_imports_rejected_rows",
        "ck_external_record_imports_issue_count",
    ):
        assert constraint in block
        assert constraint in import_block

    assert "total_rows=total_rows if total_rows is not None else len(records)" in repo
    assert "accepted_rows=len(records)" in repo
    assert "_REJECTED_ROW_ISSUE_KINDS" in repo
    assert "def _rejected_issue_count(issues: list[dict]) -> int:" in repo
    assert "rejected_rows=_rejected_issue_count(issues) if rejected_rows is None else rejected_rows" in repo
    assert "issue_count=len(issues)" in repo

    assert "ExternalRecordImportEntity" in doctor
    assert "\"external_record_imports\": {" in doctor
    assert "\"total_rows\": \"0\"" in doctor
