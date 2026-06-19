from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMAGE_READS = ROOT / "forza" / "application" / "gui_read" / "image_reads.py"


def _latest_processing_statuses_source() -> str:
    source = IMAGE_READS.read_text(encoding="utf-8")
    start = source.index("def _latest_processing_statuses")
    end = source.index("def _latest_run_input_subquery", start)
    return source[start:end]


def test_latest_processing_statuses_uses_sql_latest_result_projection() -> None:
    function_source = _latest_processing_statuses_source()

    assert "func.row_number().over" in function_source
    assert 'partition_by=ExtractionResultEntity.image_file_id' in function_source
    assert "ExtractionResultEntity.created_at.desc()" in function_source
    assert "ExtractionResultEntity.id.desc()" in function_source
    assert '.label("result_rank")' in function_source
    assert "latest_result.c.result_rank == 1" in function_source


def test_latest_processing_statuses_does_not_load_full_result_entities() -> None:
    function_source = _latest_processing_statuses_source()

    assert "select(ExtractionResultEntity)" not in function_source
    assert ".order_by(" not in function_source
    assert "for row in rows:" not in function_source


def test_latest_processing_statuses_keeps_skipped_input_fallback() -> None:
    function_source = _latest_processing_statuses_source()

    assert "missing_result_ids" in function_source
    assert "_latest_run_input_subquery()" in function_source
    assert "select(RunInputEntity)" in function_source
    assert 'statuses[row.image_file_id] = "skipped"' in function_source
