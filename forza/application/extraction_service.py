from __future__ import annotations

import logging
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from threading import Lock, local

from ..events import EventSink, EventType, emit_event
from ..exceptions import PersistenceError
from ..lmstudio import build_backend
from ..pipeline.process import process_image
from ..schemas import ExtractionResult
from .run_control import RunCancelled, RunControl

_log = logging.getLogger("forza")


class ExtractionService:
    """Process image files through the LLM pipeline and persist relational results.

    Parallel runs are cooperative: cancellation and pause are honoured at safe
    checkpoints before scheduling work and after durable per-image persistence.
    In-flight LLM calls are not force-terminated; every completed attempt/result
    is persisted before a pause/cancel checkpoint can stop the batch.
    """

    def __init__(
        self,
        *,
        database_service=None,   # DatabaseService | None — avoids circular import
        event_sink: EventSink | None = None,
        run_control: RunControl | None = None,
    ):
        self.database_service = database_service
        self.event_sink = event_sink
        self.run_control = run_control

    def process_batch(
        self,
        images: list[tuple[Path, str]],
        results: list[ExtractionResult],
        cfg,
        refs,
        run_id: str,
    ) -> None:
        if not images:
            return
        emit_event(self.event_sink, EventType.BATCH_STARTED, run_id=run_id, total=len(images))
        workers = max(1, int(cfg.workers))
        if workers > 1 and len(images) > 1:
            self._process_parallel(images, results, cfg, refs, run_id, workers=workers)
        else:
            self._process_sequential(images, results, cfg, refs, run_id)
        emit_event(self.event_sink, EventType.BATCH_FINISHED, run_id=run_id, total=len(images))

    def _process_sequential(
        self,
        images: list[tuple[Path, str]],
        results: list[ExtractionResult],
        cfg,
        refs,
        run_id: str,
    ) -> None:
        with build_backend(cfg) as backend:
            for index, (path, file_hash) in enumerate(images, start=1):
                self._checkpoint()
                result = self._process_and_record(path, file_hash, backend, refs, cfg, run_id)
                results.append(result)
                self._emit_progress(run_id, result, index, len(images))
                self._checkpoint()

    def _process_parallel(
        self,
        images: list[tuple[Path, str]],
        results: list[ExtractionResult],
        cfg,
        refs,
        run_id: str,
        *,
        workers: int,
    ) -> None:
        _log.info(f"Parallel processing with {workers} worker(s)")
        backend_pool = _ThreadBackendPool(cfg)
        executor = ThreadPoolExecutor(max_workers=workers)
        iterator = iter(images)
        in_flight: dict[Future[ExtractionResult], tuple[Path, str]] = {}
        completed = 0

        def _worker(item: tuple[Path, str]) -> ExtractionResult:
            path, file_hash = item
            self._checkpoint()
            backend = backend_pool.get()
            result = self._process_and_record(path, file_hash, backend, refs, cfg, run_id)
            self._checkpoint()
            return result

        def _submit_next() -> bool:
            self._checkpoint()
            try:
                item = next(iterator)
            except StopIteration:
                return False
            in_flight[executor.submit(_worker, item)] = item
            return True

        try:
            while len(in_flight) < workers and _submit_next():
                pass

            while in_flight:
                self._checkpoint()
                done, _pending = wait(in_flight, timeout=0.1, return_when=FIRST_COMPLETED)
                if not done:
                    continue
                for future in done:
                    item = in_flight.pop(future)
                    try:
                        result = future.result()
                    except RunCancelled:
                        raise
                    except Exception:
                        _log.error("Worker failed for %s", item[0].name, exc_info=True)
                        raise
                    results.append(result)
                    completed += 1
                    self._emit_progress(run_id, result, completed, len(images))

                while len(in_flight) < workers and _submit_next():
                    pass
        except RunCancelled:
            _cancel_futures(in_flight)
            raise
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
            backend_pool.close_all()

    def _checkpoint(self) -> None:
        if self.run_control is not None:
            self.run_control.checkpoint()

    def _process_one(self, path, file_hash, backend, refs, cfg, run_id) -> ExtractionResult:
        emit_event(
            self.event_sink,
            EventType.IMAGE_STARTED,
            run_id=run_id,
            source_file=path.name,
            file_hash=file_hash,
        )
        try:
            result = process_image(path.name, file_hash, path, backend, refs, cfg, run_id)
            if result.current_path is None:
                result.current_path = str(path)
            return result
        except RunCancelled:
            raise
        except PersistenceError:
            raise
        except Exception as exc:
            _log.error(f"Unexpected error for {path.name}: {exc}")
            return ExtractionResult(
                source_file=path.name,
                file_hash=file_hash,
                session=None,
                status="error",
                error=str(exc),
                current_path=str(path),
            )

    def _process_and_record(self, path, file_hash, backend, refs, cfg, run_id) -> ExtractionResult:
        prepared = self._prepare_result(path=path, file_hash=file_hash, run_id=run_id)
        self._configure_backend(
            backend,
            prepared=prepared,
            run_id=run_id,
            source_file=path.name,
        )
        result = self._process_one(path, file_hash, backend, refs, cfg, run_id)
        self._record_result(result, run_id, cfg)
        return result

    def _prepare_result(self, *, path: Path, file_hash: str, run_id: str):
        if self.database_service is None:
            return None
        prepare = getattr(self.database_service, "prepare_extraction_result", None)
        if not callable(prepare):
            return None
        return prepare(run_id=run_id, file_hash=file_hash, path=path)

    def _configure_backend(self, backend, *, prepared, run_id: str, source_file: str) -> None:
        configure = getattr(backend, "configure_persistence", None)
        if not callable(configure) or prepared is None or self.database_service is None:
            return

        def on_attempt(attempt) -> None:
            try:
                self.database_service.record_extraction_attempt(
                    prepared=prepared,
                    attempt=attempt,
                    run_id=run_id,
                )
            except Exception as exc:
                self._raise_persistence_failure(
                    run_id=run_id,
                    source_file=source_file,
                    phase="attempt",
                    exc=exc,
                )

        def on_runtime_snapshot(snapshot) -> str:
            try:
                return self.database_service.record_runtime_snapshot(
                    run_id=run_id,
                    diagnostic=snapshot,
                    snapshot_kind="attempt_recheck",
                )
            except Exception as exc:
                self._raise_persistence_failure(
                    run_id=run_id,
                    source_file=source_file,
                    phase="runtime_snapshot",
                    exc=exc,
                )

        configure(
            on_attempt=on_attempt,
            on_runtime_snapshot=on_runtime_snapshot,
            runtime_snapshot_id=prepared.runtime_snapshot_id,
            prompt_snapshot_id=prepared.prompt_snapshot_id,
        )

    def _raise_persistence_failure(
        self,
        *,
        run_id: str,
        source_file: str,
        phase: str,
        exc: Exception,
    ) -> None:
        _log.error(
            "[extraction] %s persistence failed for %s: %s",
            phase,
            source_file,
            exc,
            exc_info=True,
        )
        emit_event(
            self.event_sink,
            EventType.PERSISTENCE_FAILED,
            run_id=run_id,
            source_file=source_file,
            phase=phase,
            error=str(exc),
        )
        raise PersistenceError(
            f"Could not persist {phase} evidence for {source_file}: {exc}"
        ) from exc

    def _record_result(self, result: ExtractionResult, run_id: str, cfg) -> None:
        # Relational persistence is the operational source of truth. If it
        # fails, the run must fail instead of counting an unpersisted result as OK.
        if self.database_service is None:
            return
        try:
            self.database_service.upsert_image_and_laps(
                result,
                run_id=run_id,
                gamertag=cfg.gamertag,
            )
        except Exception as exc:
            _log.error(
                "[extraction] upsert_image_and_laps failed for %s: %s",
                result.source_file,
                exc,
                exc_info=True,
            )
            emit_event(
                self.event_sink,
                EventType.PERSISTENCE_FAILED,
                run_id=run_id,
                source_file=result.source_file,
                error=str(exc),
            )
            raise PersistenceError(f"Could not persist {result.source_file}: {exc}") from exc

    def _emit_progress(
        self,
        run_id: str,
        result: ExtractionResult,
        done: int,
        total: int,
    ) -> None:
        status = "OK" if result.status == "ok" else "FAIL"
        display_name = result.semantic_name or result.source_file
        suffix = f" - {result.error}" if result.status != "ok" and result.error else ""
        _log.info(f"[{done}/{total} {status}] {display_name}{suffix}")
        emit_event(
            self.event_sink,
            EventType.IMAGE_FINISHED,
            run_id=run_id,
            source_file=result.source_file,
            status=str(result.status),
            done=done,
            total=total,
        )


class _ThreadBackendPool:
    """Thread-local backend cache used by parallel extraction."""

    def __init__(self, cfg) -> None:
        self._cfg = cfg
        self._local = local()
        self._lock = Lock()
        self._backends = []

    def get(self):
        backend = getattr(self._local, "backend", None)
        if backend is None:
            backend = build_backend(self._cfg)
            self._local.backend = backend
            with self._lock:
                self._backends.append(backend)
        return backend

    def close_all(self) -> None:
        with self._lock:
            backends = list(self._backends)
            self._backends.clear()
        for backend in backends:
            try:
                backend.close()
            except Exception:
                _log.debug("[extraction] backend close failed", exc_info=True)


def _cancel_futures(futures: dict[Future[ExtractionResult], tuple[Path, str]]) -> None:
    for future in futures:
        future.cancel()
