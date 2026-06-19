from __future__ import annotations

from tests._run_service_helpers import *


def test_run_dry_run_previews_discovery_without_registering_or_extracting(monkeypatch, tmp_path) -> None:
    new_path = tmp_path / "new.png"
    duplicate_path = tmp_path / "duplicate.jpg"
    existing_path = tmp_path / "existing.png"
    nested_dir = tmp_path / "nested"
    nested_dir.mkdir()
    nested_path = nested_dir / "nested.png"
    ignored_path = nested_dir / "notes.txt"
    for path in (new_path, duplicate_path, existing_path, nested_path, ignored_path):
        path.write_text("x", encoding="utf-8")
    cfg = _cfg(tmp_path)
    database = _FakeDatabase(cfg.database_file)
    _patch_database(monkeypatch, database)
    monkeypatch.setattr(run_module, "_validate_config", lambda cfg_arg: None)
    inventory_result = SimpleNamespace(
        plan=_plan(
            total=4,
            new_images=[_new_image(new_path), _new_image(nested_path, "hash-nested")],
            duplicates=[_duplicate(duplicate_path)],
            existing_images=[_existing(existing_path)],
        )
    )
    classify_calls, register_calls = _patch_inventory(monkeypatch, inventory_result)
    extraction = _FakeExtractionService(statuses=["ok"])
    events: list[PipelineEvent] = []
    log = _FakeLog()
    service = RunService(extraction_service=extraction, event_sink=_events_sink(events))
    service.make_run_id = lambda: "run-dry"

    status = service.run(cfg, _refs(), log, options=RunOptions(dry_run=True, force=True))

    assert status == "completed"
    assert len(classify_calls) == 1
    classified_images, force, called_database = classify_calls[0]
    assert set(classified_images) == {duplicate_path, existing_path, new_path, nested_path}
    assert ignored_path not in classified_images
    assert force is True
    assert called_database is database
    assert register_calls == []
    assert extraction.calls == []
    assert database.begin_run_calls == []
    assert database.complete_run_calls == []
    assert database.fail_run_calls == []
    assert database.operation_log == []
    assert events[-1].type == "run_finished"
    assert events[-1].data == {"status": "completed", "dry_run": True, "to_process": 2}
    assert any(message == "Would process 2 image(s)" for level, message in log.messages if level == "info")

def test_run_retry_errors_processes_only_failed_images_in_input_dir(monkeypatch, tmp_path) -> None:
    retry_path = tmp_path / "retry.png"
    outside_path = tmp_path.parent / "outside-retry.png"
    missing_path = tmp_path / "missing.png"
    retry_path.write_text("x", encoding="utf-8")
    outside_path.write_text("x", encoding="utf-8")
    cfg = _cfg(tmp_path)
    database = _FakeDatabase(
        cfg.database_file,
        failed_images=[
            (retry_path, "hash-retry"),
            (outside_path, "hash-outside"),
            (missing_path, "hash-missing"),
        ],
    )
    _patch_database(monkeypatch, database)
    _patch_preflight(monkeypatch, database.operation_log)
    monkeypatch.setattr(run_module, "_validate_config", lambda cfg_arg: None)
    extraction = _FakeExtractionService(statuses=["ok"])
    rebuild = _FakeRebuildService(result=[])
    events: list[PipelineEvent] = []
    log = _FakeLog()
    service = RunService(
        extraction_service=extraction,
        rebuild_service=rebuild,
        event_sink=_events_sink(events),
    )
    service.make_run_id = lambda: "run-retry-errors"

    status = service.run(cfg, _refs(), log, options=RunOptions(retry_errors=True))

    assert status == "completed"
    assert database.begin_run_calls[0]["config"] == {"retry_errors": True}
    assert "mode" not in database.begin_run_calls[0]
    assert extraction.calls[0][0] == [(retry_path, "hash-retry")]
    assert events[1].type == "images_discovered"
    assert events[1].data["to_process"] == 1
    assert any("[retry-errors] skipped 1 failed image(s) whose file is missing" in message for level, message in log.messages if level == "warning")
    assert any("[retry-errors] skipped 1 failed image(s) outside input_dir" in message for level, message in log.messages if level == "warning")

def test_limit_selects_processable_images_after_existing_inputs(monkeypatch, tmp_path) -> None:
    existing_1 = tmp_path / "001-existing.png"
    existing_2 = tmp_path / "002-existing.png"
    new_1 = tmp_path / "003-new.png"
    new_2 = tmp_path / "004-new.png"
    new_3 = tmp_path / "005-new.png"
    _write_ordered([existing_1, existing_2, new_1, new_2, new_3])
    cfg = _cfg(tmp_path)
    database = _FakeDatabase(cfg.database_file)
    _patch_database(monkeypatch, database)
    _patch_preflight(monkeypatch, database.operation_log)
    monkeypatch.setattr(run_module, "_validate_config", lambda cfg_arg: None)

    classify_calls = []
    register_calls = []

    class _Inventory:
        def __init__(self, database_arg) -> None:
            self.database = database_arg

        def classify(self, images, *, force: bool):
            images = list(images)
            classify_calls.append((images, force, self.database))
            return SimpleNamespace(
                plan=_plan(
                    total=len(images),
                    new_images=[
                        _new_image(path, f"hash-{path.stem}")
                        for path in images
                        if "new" in path.name
                    ],
                    existing_images=[
                        _existing(path)
                        for path in images
                        if "existing" in path.name
                    ],
                )
            )

        def register(self, result_arg, *, run_id: str) -> None:
            register_calls.append((result_arg, run_id, self.database))
            database.operation_log.append("register")

    monkeypatch.setattr(image_inventory_service, "ImageInventoryService", _Inventory)
    extraction = _FakeExtractionService(statuses=["ok", "ok"])
    rebuild = _FakeRebuildService(result=[])
    events: list[PipelineEvent] = []
    service = RunService(
        extraction_service=extraction,
        rebuild_service=rebuild,
        event_sink=_events_sink(events),
    )
    service.make_run_id = lambda: "run-limit-processable"

    status = service.run(cfg, _refs(), _FakeLog(), options=RunOptions(max_images=2))

    assert status == "completed"
    assert len(classify_calls) == 1
    classified_images, force, called_database = classify_calls[0]
    assert set(classified_images) == {existing_1, existing_2, new_1, new_2, new_3}
    assert force is False
    assert called_database is database
    assert extraction.calls[0][0] == [
        (new_1, "hash-003-new"),
        (new_2, "hash-004-new"),
    ]
    assert len(register_calls) == 1
    assert events[1].type == "images_discovered"
    assert events[1].data["selection_limit"] == 2
    assert events[1].data["to_process"] == 2


def test_selected_image_files_process_only_gui_selection(monkeypatch, tmp_path) -> None:
    selected_1 = tmp_path / "001-selected.png"
    unselected = tmp_path / "002-unselected.png"
    selected_2 = tmp_path / "003-selected.png"
    _write_ordered([selected_1, unselected, selected_2])
    cfg = _cfg(tmp_path)
    database = _FakeDatabase(
        cfg.database_file,
        selected_images=[
            (selected_2, "hash-selected-2"),
            (selected_1, "hash-selected-1"),
        ],
    )
    _patch_database(monkeypatch, database)
    _patch_preflight(monkeypatch, database.operation_log)
    monkeypatch.setattr(run_module, "_validate_config", lambda cfg_arg: None)

    class _Inventory:
        def __init__(self, database_arg) -> None:
            self.database = database_arg

        def classify(self, images, *, force: bool):
            images = list(images)
            return SimpleNamespace(
                plan=_plan(
                    total=len(images),
                    new_images=[
                        _new_image(path, f"hash-{path.stem}")
                        for path in images
                    ],
                )
            )

        def register(self, result_arg, *, run_id: str) -> None:
            database.operation_log.append("register")

    monkeypatch.setattr(image_inventory_service, "ImageInventoryService", _Inventory)
    extraction = _FakeExtractionService(statuses=["ok", "ok"])
    rebuild = _FakeRebuildService(result=[])
    events: list[PipelineEvent] = []
    service = RunService(
        extraction_service=extraction,
        rebuild_service=rebuild,
        event_sink=_events_sink(events),
    )
    service.make_run_id = lambda: "run-selected"

    status = service.run(
        cfg,
        _refs(),
        _FakeLog(),
        options=RunOptions(selected_image_file_ids=("img-2", "img-1")),
    )

    assert status == "completed"
    assert database.selected_image_files_calls == [("img-2", "img-1")]
    assert database.begin_run_calls[0]["config"] == {"selected_image_file_ids": ["img-2", "img-1"]}
    assert extraction.calls[0][0] == [
        (selected_2, "hash-003-selected"),
        (selected_1, "hash-001-selected"),
    ]
    assert events[1].type == "images_discovered"
    assert events[1].data["input_total"] == 3
    assert events[1].data["selected_image_file_count"] == 2
    assert events[1].data["to_process"] == 2


def test_retry_errors_limit_selects_failed_images_after_filtering(monkeypatch, tmp_path) -> None:
    ordinary_1 = tmp_path / "001-ordinary.png"
    ordinary_2 = tmp_path / "002-ordinary.png"
    retry_1 = tmp_path / "003-retry.png"
    _write_ordered([ordinary_1, ordinary_2, retry_1])
    cfg = _cfg(tmp_path)
    database = _FakeDatabase(
        cfg.database_file,
        failed_images=[(retry_1, "hash-retry")],
    )
    _patch_database(monkeypatch, database)
    _patch_preflight(monkeypatch, database.operation_log)
    monkeypatch.setattr(run_module, "_validate_config", lambda cfg_arg: None)
    extraction = _FakeExtractionService(statuses=["ok"])
    rebuild = _FakeRebuildService(result=[])
    events: list[PipelineEvent] = []
    log = _FakeLog()
    service = RunService(
        extraction_service=extraction,
        rebuild_service=rebuild,
        event_sink=_events_sink(events),
    )
    service.make_run_id = lambda: "run-retry-limit"

    status = service.run(cfg, _refs(), log, options=RunOptions(retry_errors=True, max_images=1))

    assert status == "completed"
    assert database.begin_run_calls[0]["config"] == {"selection_limit": 1, "retry_errors": True}
    assert extraction.calls[0][0] == [(retry_1, "hash-retry")]
    assert events[1].type == "images_discovered"
    assert events[1].data["selection_limit"] == 1
    assert events[1].data["to_process"] == 1
    assert not any("outside input_dir" in message for level, message in log.messages if level == "warning")
