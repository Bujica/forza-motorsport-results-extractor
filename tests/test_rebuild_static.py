from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_rebuild_outputs_has_no_unused_results_parameter() -> None:
    source = (ROOT / "forza" / "application" / "rebuild_service.py").read_text(encoding="utf-8")

    signature = source.split("def rebuild_outputs(", 1)[1].split(") -> ReviewRefreshResult:", 1)[0]
    assert "results:" not in signature
    assert "load_runtime_history" not in source


def test_rebuild_callers_do_not_query_runtime_history_before_rebuild() -> None:
    for path in (
        ROOT / "forza" / "cli" / "rebuild.py",
        ROOT / "forza" / "gui" / "workers" / "rebuild_worker.py",
        ROOT / "forza" / "application" / "run_service.py",
    ):
        source = path.read_text(encoding="utf-8")
        assert "load_runtime_history" not in source
        assert "rebuild_outputs(results" not in source


def test_rebuild_does_not_import_external_records_or_generate_pdf_automatically() -> None:
    source = (ROOT / "forza" / "application" / "rebuild_service.py").read_text(encoding="utf-8")
    worker = (ROOT / "forza" / "gui" / "workers" / "rebuild_worker.py").read_text(encoding="utf-8")

    assert "external_records" + "_path" not in source
    assert "ExternalRecordService" not in source
    assert "replace_external_records" not in source
    assert "export_service" not in source
    assert ".pdf(" not in source
    assert "record_artifact" not in source
    assert "Generating PDF" not in source
    assert "pdf_path=None" in worker
    assert "Derived state rebuilt" in worker
