from __future__ import annotations

import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from forza.application import image_service as image_inventory_service
from forza.events import PipelineEvent
from forza.exceptions import ConfigValidationError
from forza.pipeline.image import DiscoveredImage, DuplicateImage, ExistingImage, ImageDiscoveryPlan
from forza.schemas import RunStatus
from forza.application import run_service as run_module
from forza.application.run_service import RunOptions, RunService
from forza.application.run_control import RunCancelled


class _FakeLog:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def info(self, message: str) -> None:
        self.messages.append(("info", str(message)))

    def debug(self, message: str) -> None:
        self.messages.append(("debug", str(message)))

    def warning(self, message: str) -> None:
        self.messages.append(("warning", str(message)))

    def error(self, message: str) -> None:
        self.messages.append(("error", str(message)))

    def exception(self, message: str) -> None:
        self.messages.append(("exception", str(message)))


class _FakeDatabase:
    def __init__(
        self,
        database_file: Path,
        *,
        full_results=None,
        clean_results=None,
        list_full_exc: Exception | None = None,
        failed_images=None,
        selected_images=None,
        review_case_counts: dict[str, int] | None = None,
    ) -> None:
        self.database_file = database_file
        self.full_results = full_results if full_results is not None else []
        self.clean_results = clean_results if clean_results is not None else []
        self.list_full_exc = list_full_exc
        self.failed_images = list(failed_images or [])
        self.selected_images = list(selected_images or [])
        self.selected_image_files_calls = []
        self.review_case_counts = dict(review_case_counts or {})
        self.closed = False
        self.begin_run_calls = []
        self.fail_run_calls = []
        self.complete_run_calls = []
        self.operation_log = []
        self.count_lap_records_calls = 0
        self.count_best_laps_calls = 0
        self.count_review_cases_calls = []

    def begin_run(self, **kwargs) -> None:
        self.begin_run_calls.append(kwargs)
        self.operation_log.append("begin_run")

    def count_lap_records(self):
        self.count_lap_records_calls += 1
        if self.list_full_exc is not None:
            raise self.list_full_exc
        return len(self.full_results)

    def fail_run(self, run_id: str, *, error: str) -> None:
        self.fail_run_calls.append((run_id, error))
        self.operation_log.append("fail_run")

    def complete_run(self, run_id: str, *, status=None, metrics=None) -> None:
        self.complete_run_calls.append((run_id, status, metrics or {}))
        self.operation_log.append("complete_run")

    def count_best_laps(self):
        self.count_best_laps_calls += 1
        return len(self.clean_results)

    def count_review_cases(self, *, run_id=None, status=None):
        self.count_review_cases_calls.append((run_id, status))
        return self.review_case_counts.get(run_id, 0)

    def list_failed_images_for_retry(self):
        return list(self.failed_images)

    def selected_image_files(self, image_file_ids):
        self.selected_image_files_calls.append(tuple(image_file_ids))
        return list(self.selected_images)

    def close(self) -> None:
        self.closed = True


class _FakeExtractionService:
    def __init__(self, *, statuses: list[str] | None = None, raises: Exception | None = None) -> None:
        self.statuses = statuses or []
        self.raises = raises
        self.calls = []

    def process_batch(self, new_images, current_results, cfg, refs, run_id: str) -> None:
        self.calls.append((new_images, cfg, refs, run_id))
        for status in self.statuses:
            current_results.append(SimpleNamespace(status=status))
        if self.raises is not None:
            raise self.raises


class _FakeRebuildService:
    def __init__(self, result=None) -> None:
        self.result = [] if result is None else result
        self.calls = []

    def rebuild_outputs(self, cfg, refs, log, *, run_id: str):
        self.calls.append((cfg, refs, log, run_id))
        return self.result


class _FakePreflightBackend:
    def __init__(self, operation_log: list[str], *, raises: Exception | None = None) -> None:
        self.operation_log = operation_log
        self.raises = raises

    def __enter__(self):
        self.operation_log.append("preflight")
        if self.raises is not None:
            raise self.raises
        return self

    def __exit__(self, *_args):
        return None


def _cfg(input_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(
        database_file=Path("data/forza.sqlite3"),
        input_dir=input_dir,
        gamertag="Bujica89",
        workers=3,
        llm=SimpleNamespace(model="model-a"),
        prompt=SimpleNamespace(active="prompt-v1"),
    )


def _refs() -> SimpleNamespace:
    return SimpleNamespace(tracks=["Track"], cars=["Car"])


def _write_ordered(paths: list[Path]) -> None:
    base_mtime = 1_700_000_000
    for index, path in enumerate(paths):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"image-{index}", encoding="utf-8")
        timestamp = base_mtime + index
        os.utime(path, (timestamp, timestamp))


def _new_image(path: Path, file_hash: str = "hash-new") -> DiscoveredImage:
    return DiscoveredImage(path=path, file_hash=file_hash)


def _duplicate(path: Path) -> DuplicateImage:
    return DuplicateImage(path=path, file_hash="hash-dup", reason="cached", duplicate_of_hash="hash-original")


def _existing(path: Path) -> ExistingImage:
    return ExistingImage(path=path, file_hash="hash-existing")


def _plan(*, total: int, new_images=None, duplicates=None, existing_images=None) -> ImageDiscoveryPlan:
    return ImageDiscoveryPlan(
        total=total,
        new_images=list(new_images or []),
        duplicates=list(duplicates or []),
        existing_images=list(existing_images or []),
    )


def _patch_database(monkeypatch, database: _FakeDatabase):
    created = []

    def make_database(database_file: Path):
        assert database_file == database.database_file
        created.append(database)
        return database

    monkeypatch.setattr(run_module, "DatabaseService", make_database)
    return created


def _patch_inventory(monkeypatch, result):
    classify_calls = []
    register_calls = []

    class _FakeInventory:
        def __init__(self, database) -> None:
            self.database = database

        def classify(self, images, *, force: bool):
            classify_calls.append((list(images), force, self.database))
            return result

        def register(self, result_arg, *, run_id: str) -> None:
            register_calls.append((result_arg, run_id, self.database))
            if hasattr(self.database, "operation_log"):
                self.database.operation_log.append("register")

    monkeypatch.setattr(image_inventory_service, "ImageInventoryService", _FakeInventory)
    return classify_calls, register_calls


def _patch_preflight(monkeypatch, operation_log: list[str], *, raises: Exception | None = None) -> None:
    monkeypatch.setattr(
        run_module,
        "build_backend",
        lambda _cfg: _FakePreflightBackend(operation_log, raises=raises),
    )


def _events_sink(events: list[PipelineEvent]):
    return lambda event: events.append(event)

__all__ = [
    'os',
    're',
    'Path',
    'SimpleNamespace',
    'pytest',
    'image_inventory_service',
    'PipelineEvent',
    'ConfigValidationError',
    'DiscoveredImage',
    'DuplicateImage',
    'ExistingImage',
    'ImageDiscoveryPlan',
    'RunStatus',
    'run_module',
    'RunOptions',
    'RunService',
    'RunCancelled',
    '_FakeLog',
    '_FakeDatabase',
    '_FakeExtractionService',
    '_FakeRebuildService',
    '_FakePreflightBackend',
    '_cfg',
    '_refs',
    '_write_ordered',
    '_new_image',
    '_duplicate',
    '_existing',
    '_plan',
    '_patch_database',
    '_patch_inventory',
    '_patch_preflight',
    '_events_sink',
]
