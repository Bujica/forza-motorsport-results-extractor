"""Clean-break DB baseline.

Revision ID: 0001_db_vnext_baseline
Revises:
Create Date: 2026-06-09
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from alembic import op


revision = "0001_db_vnext_baseline"
down_revision = None
branch_labels = None
depends_on = None

_BASELINE_SQL_FILES = (
    "0001_db_vnext_schema.sql",
)


def upgrade() -> None:
    bind = op.get_bind()
    schema_dir = Path(__file__).parent
    for schema_name in _BASELINE_SQL_FILES:
        schema_file = schema_dir / schema_name
        for statement in _iter_sql_statements(schema_file.read_text(encoding="utf-8")):
            bind.exec_driver_sql(statement)


def _iter_sql_statements(script: str) -> Iterator[str]:
    buffer: list[str] = []
    in_trigger = False
    for raw_line in script.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("--"):
            continue
        if line.casefold().startswith("create trigger "):
            in_trigger = True
        buffer.append(raw_line)
        if in_trigger:
            if line.casefold() == "end;":
                statement = "\n".join(buffer).strip()
                if statement:
                    yield statement
                buffer.clear()
                in_trigger = False
        elif line.endswith(";"):
            statement = "\n".join(buffer).strip().removesuffix(";").strip()
            if statement:
                yield statement
            buffer.clear()
    if buffer:
        statement = "\n".join(buffer).strip().removesuffix(";").strip()
        if statement:
            yield statement


def downgrade() -> None:
    for table in (
        "image_files",
        "run_inputs",
        "review_cases",
        "reference_tracks",
        "reference_cars",
        "prompt_snapshots",
        "model_runtime_snapshots",
        "model_artifacts",
        "lap_records",
        "image_flags",
        "extraction_runs",
        "extraction_results",
        "extraction_attempts",
        "external_record_imports",
        "external_lap_records",
        "export_artifacts",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
