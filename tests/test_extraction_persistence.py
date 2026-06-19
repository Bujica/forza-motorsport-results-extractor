from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from forza.events import PipelineEvent
from forza.exceptions import PersistenceError
from forza.schemas import ExtractionResult, LapRecord, RaceSession
from forza.application.extraction_service import ExtractionService


class _Backend:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass


class _FailingDb:
    def upsert_image_and_laps(self, result, *, run_id: str, gamertag: str):
        raise RuntimeError("database is locked")


class _AttemptFailingDb:
    def prepare_extraction_result(self, *, run_id: str, file_hash: str, path: Path):
        return SimpleNamespace(
            runtime_snapshot_id="runtime-1",
            prompt_snapshot_id="prompt-1",
        )

    def record_extraction_attempt(self, **_kwargs):
        raise RuntimeError("attempt insert failed")


class _CallbackBackend(_Backend):
    def configure_persistence(self, **callbacks):
        self.on_attempt = callbacks["on_attempt"]


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(workers=1, gamertag="Bujica89")


def _result(source_file: str, file_hash: str) -> ExtractionResult:
    session = RaceSession(
        track="Track",
        temp_f=70.0,
        temp_c=21.1,
        entries=[LapRecord("Driver", "Car", "A", "1:00.000", 60000, False)],
        race_class="A",
        weather="dry",
    )
    return ExtractionResult(
        source_file=source_file,
        file_hash=file_hash,
        session=session,
        status="ok",
    )


def test_persistence_failure_aborts_batch_and_emits_event(monkeypatch, tmp_path) -> None:
    events: list[PipelineEvent] = []

    monkeypatch.setattr("forza.application.extraction_service.build_backend", lambda cfg: _Backend())
    monkeypatch.setattr(
        "forza.application.extraction_service.process_image",
        lambda filename, hash_value, image_path, backend, refs, cfg, run_id: _result(filename, hash_value),
    )

    service = ExtractionService(
        database_service=_FailingDb(),
        event_sink=events.append,
    )
    results: list[ExtractionResult] = []

    with pytest.raises(PersistenceError, match="Could not persist first.png"):
        service.process_batch(
            [(tmp_path / "first.png", "hash-1")],
            results,
            _cfg(),
            refs=object(),
            run_id="run-1",
        )

    assert results == []
    persistence_events = [event for event in events if event.type == "persistence_failed"]
    assert len(persistence_events) == 1
    assert persistence_events[0].run_id == "run-1"
    assert persistence_events[0].data["source_file"] == "first.png"
    assert "database is locked" in persistence_events[0].data["error"]


def test_attempt_persistence_failure_is_not_downgraded_to_result_error(monkeypatch, tmp_path) -> None:
    events: list[PipelineEvent] = []

    monkeypatch.setattr(
        "forza.application.extraction_service.build_backend",
        lambda cfg: _CallbackBackend(),
    )

    def process_with_attempt(filename, hash_value, image_path, backend, refs, cfg, run_id):
        backend.on_attempt(SimpleNamespace(attempt_number=1))
        return _result(filename, hash_value)

    monkeypatch.setattr(
        "forza.application.extraction_service.process_image",
        process_with_attempt,
    )
    service = ExtractionService(
        database_service=_AttemptFailingDb(),
        event_sink=events.append,
    )
    results: list[ExtractionResult] = []

    with pytest.raises(PersistenceError, match="attempt evidence"):
        service.process_batch(
            [(tmp_path / "first.png", "hash-1")],
            results,
            _cfg(),
            refs=object(),
            run_id="run-1",
        )

    assert results == []
    [event] = [event for event in events if event.type == "persistence_failed"]
    assert event.data["phase"] == "attempt"
