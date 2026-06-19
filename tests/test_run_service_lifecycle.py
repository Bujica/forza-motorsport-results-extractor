from __future__ import annotations

from tests._run_service_helpers import *


def test_run_returns_failed_when_config_validation_fails(monkeypatch, tmp_path) -> None:
    cfg = _cfg(tmp_path)
    log = _FakeLog()
    monkeypatch.setattr(run_module, "_validate_config", lambda cfg_arg: (_ for _ in ()).throw(ConfigValidationError("bad config")))
    monkeypatch.setattr(run_module, "DatabaseService", lambda database_file: pytest.fail("database should not open"))

    assert RunService().run(cfg, _refs(), log) == "failed"
    assert ("error", "bad config") in log.messages

def test_run_fails_and_closes_database_when_input_dir_is_missing(monkeypatch, tmp_path) -> None:
    cfg = _cfg(tmp_path / "missing")
    database = _FakeDatabase(cfg.database_file, full_results=[object()])
    events: list[PipelineEvent] = []
    _patch_database(monkeypatch, database)
    monkeypatch.setattr(run_module, "_validate_config", lambda cfg_arg: None)
    service = RunService(event_sink=_events_sink(events))
    service.make_run_id = lambda: "run-1"

    status = service.run(cfg, _refs(), _FakeLog())

    assert status == "failed"
    assert database.begin_run_calls == [
        {
            "run_id": "run-1",
            "backend": "lmstudio",
            "model": "model-a",
            "prompt_name": "prompt-v1",
            "input_dir": str(cfg.input_dir),
            "workers": cfg.workers,
        }
    ]
    assert database.fail_run_calls == [("run-1", "input_dir_missing")]
    assert database.closed is True
    assert [(event.type, event.run_id, event.data) for event in events] == [
        ("run_started", "run-1", {}),
        ("run_finished", "run-1", {"status": "failed", "error": "input_dir_missing"}),
    ]

def test_run_completed_registers_inventory_processes_images_and_rebuilds(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "new.png"
    image_path.write_text("x", encoding="utf-8")
    cfg = _cfg(tmp_path)
    database = _FakeDatabase(
        cfg.database_file,
        clean_results=[1, 2, 3],
        review_case_counts={"run-complete": 1},
    )
    _patch_database(monkeypatch, database)
    _patch_preflight(monkeypatch, database.operation_log)
    monkeypatch.setattr(run_module, "_validate_config", lambda cfg_arg: None)
    inventory_result = SimpleNamespace(plan=_plan(total=1, new_images=[_new_image(image_path, "hash-1")]))
    _classify_calls, register_calls = _patch_inventory(monkeypatch, inventory_result)
    extraction = _FakeExtractionService(statuses=["ok", "error"])
    rebuild = _FakeRebuildService(result=["review-1", "review-2"])
    events: list[PipelineEvent] = []
    service = RunService(
        extraction_service=extraction,
        rebuild_service=rebuild,
        event_sink=_events_sink(events),
    )
    service.make_run_id = lambda: "run-complete"
    monkeypatch.setattr(run_module.time, "monotonic", iter([10.0, 12.345]).__next__)

    status = service.run(cfg, _refs(), _FakeLog())

    assert status == "completed"
    assert database.operation_log.index("preflight") < database.operation_log.index("register")
    assert register_calls == [(inventory_result, "run-complete", database)]
    assert extraction.calls == [([(image_path, "hash-1")], cfg, _refs(), "run-complete")]
    # The extraction call stores the refs object by identity; compare stable fields instead of object identity.
    called_new_images, called_cfg, called_refs, called_run_id = extraction.calls[0]
    assert called_new_images == [(image_path, "hash-1")]
    assert called_cfg is cfg
    assert called_refs.tracks == ["Track"]
    assert called_run_id == "run-complete"
    assert rebuild.calls[0][0] is cfg
    assert rebuild.calls[0][3] == "run-complete"
    assert database.complete_run_calls == [
        (
            "run-complete",
            None,
            {
                "processed": 2,
                "succeeded": 1,
                "failed": 1,
                "review_case_count": 1,
                "elapsed_s": 2.35,
            },
        )
    ]
    assert database.count_best_laps_calls == 1
    assert database.count_review_cases_calls == [("run-complete", "open")]
    assert events[-1].data == {
        "status": "completed",
        "processed": 2,
        "errors": 1,
        "duplicates": 0,
        "review_cases": 1,
        "global_review_cases": 2,
        "clean_snapshot": 3,
        "elapsed_s": pytest.approx(2.345),
    }

def test_run_completed_with_no_new_images_skips_extraction(monkeypatch, tmp_path) -> None:
    cfg = _cfg(tmp_path)
    tmp_path.mkdir(exist_ok=True)
    database = _FakeDatabase(cfg.database_file)
    _patch_database(monkeypatch, database)
    _patch_preflight(monkeypatch, database.operation_log)
    monkeypatch.setattr(run_module, "_validate_config", lambda cfg_arg: None)
    inventory_result = SimpleNamespace(plan=_plan(total=0))
    _classify_calls, register_calls = _patch_inventory(monkeypatch, inventory_result)
    extraction = _FakeExtractionService(statuses=["ok"])
    rebuild = _FakeRebuildService(result=[])
    service = RunService(extraction_service=extraction, rebuild_service=rebuild)
    service.make_run_id = lambda: "run-empty"

    status = service.run(cfg, _refs(), _FakeLog())

    assert status == "completed"
    assert register_calls == [(inventory_result, "run-empty", database)]
    assert extraction.calls == []
    assert database.complete_run_calls[0][2]["processed"] == 0

def test_run_warns_when_gamertag_is_default(monkeypatch, tmp_path) -> None:
    cfg = _cfg(tmp_path / "missing")
    cfg.gamertag = "Player"
    database = _FakeDatabase(cfg.database_file)
    _patch_database(monkeypatch, database)
    monkeypatch.setattr(run_module, "_validate_config", lambda cfg_arg: None)
    log = _FakeLog()
    service = RunService()
    service.make_run_id = lambda: "run-default-player"

    assert service.run(cfg, _refs(), log) == "failed"

    assert any(
        level == "warning" and "gamertag is not set" in message
        for level, message in log.messages
    )
