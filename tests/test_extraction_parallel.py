from __future__ import annotations

from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest

from forza.schemas import ExtractionResult, LapRecord, RaceSession
from forza.application.extraction_service import ExtractionService
from forza.application.run_control import RunCancelled, RunControl


class _FakeBackend:
    close_count = 0
    instances = []

    def __init__(self) -> None:
        self.closed = False
        _FakeBackend.instances.append(self)

    def close(self) -> None:
        self.closed = True
        _FakeBackend.close_count += 1

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class _Db:
    def __init__(self, *, cancel_on_upsert: RunControl | None = None) -> None:
        self.rows: list[str] = []
        self.cancel_on_upsert = cancel_on_upsert

    def upsert_image_and_laps(self, result, *, run_id: str, gamertag: str):
        if self.cancel_on_upsert is not None:
            self.cancel_on_upsert.cancel()
        self.rows.append(result.source_file)
        return 1


def _cfg(workers: int) -> SimpleNamespace:
    return SimpleNamespace(workers=workers, gamertag="Bujica89")


def _result(source_file: str, file_hash: str) -> ExtractionResult:
    session = RaceSession(
        track="Track",
        temp_f=70.0,
        temp_c=21.1,
        entries=[LapRecord("Driver", "Car", "A", "1:00.000", 60.0, False)],
        race_class="A",
        weather="dry",
    )
    return ExtractionResult(
        source_file=source_file,
        file_hash=file_hash,
        session=session,
        status="ok",
    )


def test_one_worker_uses_single_backend(monkeypatch, tmp_path):
    calls = []
    _FakeBackend.close_count = 0
    _FakeBackend.instances = []

    def fake_build_backend(cfg):
        return _FakeBackend()

    def fake_process_image(filename, hash_value, image_path, backend, refs, cfg, run_id):
        calls.append((filename, id(backend)))
        return _result(filename, hash_value)

    monkeypatch.setattr("forza.application.extraction_service.build_backend", fake_build_backend)
    monkeypatch.setattr("forza.application.extraction_service.process_image", fake_process_image)

    db = _Db()
    control = RunControl()
    service = ExtractionService(database_service=db, run_control=control)
    images = [(tmp_path / f"{idx}.png", f"hash-{idx}") for idx in range(4)]
    results = []

    service.process_batch(images, results, _cfg(workers=1), refs=object(), run_id="run-1")

    assert sorted(result.source_file for result in results) == ["0.png", "1.png", "2.png", "3.png"]
    assert sorted(db.rows) == ["0.png", "1.png", "2.png", "3.png"]
    assert len(calls) == 4
    assert len(_FakeBackend.instances) == 1
    assert _FakeBackend.close_count == len(_FakeBackend.instances)


def test_multiple_workers_use_parallel_backends(monkeypatch, tmp_path):
    calls = []
    barrier = Barrier(2)
    _FakeBackend.close_count = 0
    _FakeBackend.instances = []

    def fake_build_backend(cfg):
        return _FakeBackend()

    def fake_process_image(filename, hash_value, image_path, backend, refs, cfg, run_id):
        calls.append((filename, id(backend)))
        if filename in {"0.png", "1.png"}:
            barrier.wait(timeout=5)
        return _result(filename, hash_value)

    monkeypatch.setattr("forza.application.extraction_service.build_backend", fake_build_backend)
    monkeypatch.setattr("forza.application.extraction_service.process_image", fake_process_image)

    db = _Db()
    control = RunControl()
    service = ExtractionService(database_service=db, run_control=control)
    images = [(tmp_path / f"{idx}.png", f"hash-{idx}") for idx in range(4)]
    results = []

    service.process_batch(
        images,
        results,
        _cfg(workers=2),
        refs=object(),
        run_id="run-1",
    )

    assert sorted(result.source_file for result in results) == ["0.png", "1.png", "2.png", "3.png"]
    assert sorted(db.rows) == ["0.png", "1.png", "2.png", "3.png"]
    assert len(calls) == 4
    assert len(_FakeBackend.instances) == 2
    assert _FakeBackend.close_count == len(_FakeBackend.instances)


def test_parallel_extraction_cancellation_keeps_durable_result_before_checkpoint(monkeypatch, tmp_path):
    def fake_build_backend(cfg):
        return _FakeBackend()

    def fake_process_image(filename, hash_value, image_path, backend, refs, cfg, run_id):
        return _result(filename, hash_value)

    monkeypatch.setattr("forza.application.extraction_service.build_backend", fake_build_backend)
    monkeypatch.setattr("forza.application.extraction_service.process_image", fake_process_image)

    control = RunControl()
    db = _Db(cancel_on_upsert=control)
    service = ExtractionService(database_service=db, run_control=control)
    images = [(tmp_path / f"{idx}.png", f"hash-{idx}") for idx in range(5)]
    results = []

    with pytest.raises(RunCancelled):
        service.process_batch(
            images,
            results,
            _cfg(workers=3),
            refs=object(),
            run_id="run-1",
        )

    assert len(db.rows) == 1
    assert results == []
