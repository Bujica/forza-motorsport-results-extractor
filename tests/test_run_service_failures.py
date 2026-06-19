from __future__ import annotations

from tests._run_service_helpers import *


def test_run_preflight_failure_fails_run_without_registering_or_extracting(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "new.png"
    image_path.write_text("x", encoding="utf-8")
    cfg = _cfg(tmp_path)
    database = _FakeDatabase(cfg.database_file)
    _patch_database(monkeypatch, database)
    _patch_preflight(monkeypatch, database.operation_log, raises=RuntimeError("models endpoint down"))
    monkeypatch.setattr(run_module, "_validate_config", lambda cfg_arg: None)
    inventory_result = SimpleNamespace(plan=_plan(total=1, new_images=[_new_image(image_path, "hash-1")]))
    _classify_calls, register_calls = _patch_inventory(monkeypatch, inventory_result)
    extraction = _FakeExtractionService(statuses=["ok"])
    events: list[PipelineEvent] = []
    log = _FakeLog()
    service = RunService(extraction_service=extraction, event_sink=_events_sink(events))
    service.make_run_id = lambda: "run-preflight-fail"

    status = service.run(cfg, _refs(), log)

    assert status == "failed"
    assert register_calls == []
    assert extraction.calls == []
    assert database.fail_run_calls[0][0] == "run-preflight-fail"
    assert "lmstudio_preflight_failed" in database.fail_run_calls[0][1]
    assert events[-1].data["status"] == "failed"
    assert "models endpoint down" in events[-1].data["error"]

def test_run_cancelled_completes_run_as_cancelled(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "new.png"
    image_path.write_text("x", encoding="utf-8")
    cfg = _cfg(tmp_path)
    database = _FakeDatabase(cfg.database_file)
    _patch_database(monkeypatch, database)
    _patch_preflight(monkeypatch, database.operation_log)
    monkeypatch.setattr(run_module, "_validate_config", lambda cfg_arg: None)
    inventory_result = SimpleNamespace(plan=_plan(total=1, new_images=[_new_image(image_path)]))
    _patch_inventory(monkeypatch, inventory_result)
    extraction = _FakeExtractionService(statuses=["ok", "error"], raises=RunCancelled())
    events: list[PipelineEvent] = []
    service = RunService(extraction_service=extraction, event_sink=_events_sink(events))
    service.make_run_id = lambda: "run-cancelled"

    status = service.run(cfg, _refs(), _FakeLog())

    assert status == "cancelled"
    assert database.complete_run_calls == [
        (
            "run-cancelled",
            RunStatus.CANCELLED,
            {"operational_error_message": "cancelled_by_user"},
        )
    ]
    assert events[-1].data == {"status": "cancelled"}

def test_run_unhandled_exception_marks_run_failed_closes_database_and_reraises(monkeypatch, tmp_path) -> None:
    cfg = _cfg(tmp_path)
    tmp_path.mkdir(exist_ok=True)
    database = _FakeDatabase(cfg.database_file, list_full_exc=RuntimeError("boom"))
    _patch_database(monkeypatch, database)
    monkeypatch.setattr(run_module, "_validate_config", lambda cfg_arg: None)
    events: list[PipelineEvent] = []
    log = _FakeLog()
    service = RunService(event_sink=_events_sink(events))
    service.make_run_id = lambda: "run-boom"

    with pytest.raises(RuntimeError, match="boom"):
        service.run(cfg, _refs(), log)

    assert database.fail_run_calls == [("run-boom", "boom")]
    assert database.closed is True
    assert events[-1].type == "run_finished"
    assert events[-1].data == {"status": "failed"}
    assert any(level == "exception" and "Unhandled exception" in message for level, message in log.messages)

def test_run_logs_failure_to_reconcile_unhandled_exception(monkeypatch, tmp_path) -> None:
    cfg = _cfg(tmp_path)
    tmp_path.mkdir(exist_ok=True)
    database = _FakeDatabase(cfg.database_file, list_full_exc=RuntimeError("boom"))
    database.fail_run = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("database unavailable")
    )
    _patch_database(monkeypatch, database)
    monkeypatch.setattr(run_module, "_validate_config", lambda cfg_arg: None)
    log = _FakeLog()
    service = RunService()
    service.make_run_id = lambda: "run-reconcile-fail"

    with pytest.raises(RuntimeError, match="boom"):
        service.run(cfg, _refs(), log)

    assert database.closed is True
    assert any(
        level == "exception"
        and "Could not reconcile failed run run-reconcile-fail: database unavailable" in message
        for level, message in log.messages
    )

def test_run_unhandled_exception_ignores_secondary_fail_run_failure(monkeypatch, tmp_path) -> None:
    cfg = _cfg(tmp_path)
    tmp_path.mkdir(exist_ok=True)
    database = _FakeDatabase(cfg.database_file, list_full_exc=RuntimeError("primary boom"))
    _patch_database(monkeypatch, database)
    monkeypatch.setattr(run_module, "_validate_config", lambda cfg_arg: None)
    events: list[PipelineEvent] = []

    def fail_run_raises(run_id: str, *, error: str) -> None:
        raise RuntimeError("secondary boom")

    database.fail_run = fail_run_raises
    service = RunService(event_sink=_events_sink(events))
    service.make_run_id = lambda: "run-secondary-failure"

    with pytest.raises(RuntimeError, match="primary boom"):
        service.run(cfg, _refs(), _FakeLog())

    assert database.closed is True
    assert events[-1].type == "run_finished"
    assert events[-1].data == {"status": "failed"}


def test_lmstudio_preflight_uses_single_runtime_snapshot_helper() -> None:
    source = (Path(__file__).resolve().parents[1] / "forza" / "application" / "run_service.py").read_text(encoding="utf-8")
    preflight_body = source.split("def _preflight_lmstudio", 1)[1].split("def _record_lmstudio_runtime_snapshot", 1)[0]
    snapshot_body = source.split("def _record_lmstudio_runtime_snapshot", 1)[1].split("def _extraction", 1)[0]

    assert "def _lmstudio_preflight_context" in source
    assert "class _LMStudioPreflightContext" in source
    assert preflight_body.count("_record_lmstudio_runtime_snapshot(") == 2
    assert "LMStudioRuntimeClient" not in preflight_body
    assert snapshot_body.count("LMStudioRuntimeClient") == 1
    assert source.count("desired_load_config={") == 1

