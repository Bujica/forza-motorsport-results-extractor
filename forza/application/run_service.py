from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from ..config import validate_config as _validate_config
from ..db.models import utc_now
from ..events import EventSink, EventType, emit_event
from ..exceptions import ConfigValidationError
from ..lmstudio import LMSTUDIO_BACKEND_NAME, build_backend
from ..lmstudio.client import LMStudioRuntimeClient
from ..pipeline import (
    SUPPORTED_IMAGE_EXTENSIONS,
    DiscoveredImage,
    ImageDiscoveryPlan,
    SkippedImage,
    find_input_files,
)
from ..schemas import RunMode, RunStatus
from .database_service import DatabaseService
from .extraction_service import ExtractionService
from .rebuild_service import RebuildService
from .run_control import RunCancelled, RunControl


@dataclass(frozen=True)
class RunOptions:
    dry_run: bool = False
    force: bool = False
    retry_errors: bool = False
    max_images: int | None = None
    selected_image_file_ids: tuple[str, ...] | None = None


@dataclass(frozen=True)
class _LMStudioPreflightContext:
    model: str
    endpoint: str
    desired_load_config: dict[str, object]


class RunService:
    """Application boundary for screenshot processing runs."""

    def __init__(
        self,
        *,
        extraction_service: ExtractionService | None = None,
        rebuild_service: RebuildService | None = None,
        event_sink: EventSink | None = None,
        run_control: RunControl | None = None,
    ):
        self.extraction_service = extraction_service
        self.rebuild_service = rebuild_service
        self.event_sink = event_sink
        self.run_control = run_control

    def run(self, cfg, refs, log, *, options: RunOptions | None = None) -> str:
        options = options or RunOptions()
        if options.force and options.retry_errors:
            log.error("--force and --retry-errors cannot be combined.")
            return "failed"
        if options.max_images is not None and options.max_images <= 0:
            log.error("--limit must be greater than zero when provided.")
            return "failed"

        # ── Pre-flight validation ─────────────────────────────────────────────
        try:
            _validate_config(cfg)
        except ConfigValidationError as exc:
            log.error(str(exc))
            return "failed"

        if not cfg.gamertag or cfg.gamertag == "Player":
            log.warning("[config] gamertag is not set; results will be attributed to 'Player'")

        run_id = self.make_run_id()
        log.info("=" * 50)
        log.info(f"Forza Motorsport Results Extractor  run={run_id}")

        # ── Open a shared database service for the lifetime of this run ───────
        database = DatabaseService(cfg.database_file)

        try:
            reconcile_abandoned = getattr(database, "reconcile_abandoned_runs", None)
            recovered = reconcile_abandoned() if callable(reconcile_abandoned) else 0
            if recovered:
                log.warning(f"[run] Reconciled {recovered} abandoned run(s) before starting")
            return self._run_body(cfg, refs, log, options, run_id, database)
        except Exception as exc:
            log.exception(f"[run] Unhandled exception in run {run_id}: {exc}")
            try:
                reconcile = getattr(database, "reconcile_interrupted_run", None)
                if callable(reconcile):
                    reconcile(
                        run_id,
                        status=RunStatus.FAILED,
                        error=f"run_failed: {exc}",
                    )
                else:
                    database.fail_run(run_id, error=str(exc))
            except Exception as reconcile_exc:
                log.exception(
                    f"[run] Could not reconcile failed run {run_id}: {reconcile_exc}"
                )
            emit_event(
                self.event_sink, EventType.RUN_FINISHED, run_id=run_id, status="failed"
            )
            raise
        finally:
            database.close()

    def _run_body(self, cfg, refs, log, options, run_id, database) -> str:
        emit_event(self.event_sink, EventType.RUN_STARTED, run_id=run_id)
        t_start = time.monotonic()
        current_results: list = []

        log.info(
            f"References loaded - tracks: {len(refs.tracks)}, cars: {len(refs.cars)}"
        )
        log.info(
            f"Gamertag: {cfg.gamertag} | "
            f"Backend: {LMSTUDIO_BACKEND_NAME} | "
            f"Execution: {_execution_mode(cfg.workers)} | "
            f"Prompt: {cfg.prompt.active}"
        )

        # Create persistent run rows for real processing only. Dry-run is a
        # read-only planning command used by humans and release-audit gates.
        if not options.dry_run:
            database.begin_run(**_begin_run_kwargs(cfg, run_id, options))

        try:
            self._checkpoint()
            historical_count = database.count_lap_records()
            log.info(f"Relational history: {historical_count} record(s)")

            if not cfg.input_dir.exists():
                message = f"Input directory not found: {cfg.input_dir}"
                log.error(message)
                if not options.dry_run:
                    database.fail_run(run_id, error="input_dir_missing")
                emit_event(
                    self.event_sink,
                    EventType.RUN_FINISHED,
                    run_id=run_id,
                    status="failed",
                    error="input_dir_missing",
                )
                return "failed"

            input_files = sorted(find_input_files(cfg.input_dir), key=_mtime_sort_key)
            input_images = [
                path for path in input_files
                if path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
            ]
            selected_files = _selected_files(database, options)
            all_files = [path for path, _hash in selected_files] if selected_files is not None else input_files
            all_images = [
                path for path in all_files
                if path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
            ]
            inventory_result = None
            if options.retry_errors:
                discovery, _retry_images = self._retry_error_discovery(database, all_images, log)
                discovery = _limit_discovery_processable(
                    discovery,
                    options.max_images,
                    log,
                    label="retry image",
                )
            else:
                from .image_service import ImageInventoryResult, ImageInventoryService

                inventory = ImageInventoryService(database)
                inventory_result = inventory.classify(all_images, force=options.force)
                limited_discovery = _limit_discovery_processable(
                    inventory_result.plan,
                    options.max_images,
                    log,
                    label="processable image",
                )
                if limited_discovery is not inventory_result.plan:
                    inventory_result = ImageInventoryResult(
                        plan=limited_discovery,
                        new_count=limited_discovery.process_count,
                        existing_count=len(limited_discovery.existing_images),
                        duplicate_count=limited_discovery.duplicate_count,
                    )
                discovery = limited_discovery
            new_images = [(item.path, item.file_hash) for item in discovery.new_images]
            discovery = _account_for_unselected_files(
                discovery,
                all_files=all_files,
                selected_images=all_images,
            )

            event_data = _selection_payload(
                total=discovery.total,
                input_total=len(input_files),
                selection_limit=options.max_images,
                selected_count=len(selected_files) if selected_files is not None else None,
                existing=len(discovery.existing_images),
                duplicates=discovery.duplicate_count,
                to_process=discovery.process_count,
                dry_run=options.dry_run,
                retry_errors=options.retry_errors,
            )
            emit_event(self.event_sink, EventType.IMAGES_DISCOVERED, run_id=run_id, **event_data)
            limit_note = (
                f", selection limit={options.max_images} of {len(all_images)} supported image(s)"
                if options.max_images is not None
                else ""
            )
            if options.max_images is None:
                log.info(
                    f"Input: {discovery.total} total, "
                    f"{len(discovery.existing_images)} existing, "
                    f"{discovery.duplicate_count} duplicate(s) skipped, "
                    f"{discovery.process_count} to process"
                )
            else:
                log.info(
                    f"Input: {discovery.process_count} selected to process of {len(all_images)} supported image(s){limit_note}, "
                    f"{len(discovery.existing_images)} existing, "
                    f"{discovery.duplicate_count} duplicate(s) skipped, "
                    f"{discovery.process_count} to process"
                )
            if selected_files is not None:
                log.info(
                    f"[selection] using {len(selected_files)} selected image(s) "
                    f"from Images out of {len(input_images)} supported input image(s)"
                )
            if not options.dry_run and hasattr(database, "record_discovery_inputs"):
                database.record_discovery_inputs(
                    run_id=run_id,
                    discovery=discovery,
                    process_reason="retry_errors" if options.retry_errors else "force" if options.force else "full_run",
                    dry_run=options.dry_run,
                )

            if options.dry_run:
                self._checkpoint()
                self._log_discovery_preview(log, discovery, new_images)
                emit_event(
                    self.event_sink,
                    EventType.RUN_FINISHED,
                    run_id=run_id,
                    **_with_selection_limit(
                        {"status": "completed", "dry_run": True, "to_process": len(new_images)},
                        options,
                    ),
                )
                return "completed"

            self._checkpoint()
            if new_images and not self._preflight_lmstudio(cfg, log, run_id, database):
                return "failed"

            self._checkpoint()
            if inventory_result is not None:
                inventory.register(inventory_result, run_id=run_id)

            if not new_images and options.retry_errors:
                log.info("No failed images to retry.")
            elif not new_images:
                log.info("No new images to process.")
            else:
                self._extraction(database).process_batch(
                    new_images, current_results, cfg, refs, run_id
                )

            self._checkpoint()

            ok_count = sum(1 for result in current_results if result.status == "ok")
            fail_count = sum(1 for result in current_results if result.status == "error")
            log.info(f"Processing complete: {ok_count} OK, {fail_count} failed")

            review_result = self._rebuild(database).rebuild_outputs(
                cfg,
                refs,
                log,
                run_id=run_id,
            )

            elapsed = self._elapsed_since(t_start)
            cleaned_len = database.count_best_laps()
            global_review_cases = len(review_result) if isinstance(review_result, list) else 0
            review_cases = database.count_review_cases(run_id=run_id, status="open")

            database.complete_run(
                run_id,
                metrics=_with_selection_limit(
                    {
                        "processed": ok_count + fail_count,
                        "succeeded": ok_count,
                        "failed": fail_count,
                        "review_case_count": review_cases,
                        "elapsed_s": round(elapsed, 2),
                    },
                    options,
                ),
            )

            log.info(
                f"[run] completed run={run_id} ok={ok_count} err={fail_count} "
                f"dup={discovery.duplicate_count} review={review_cases} "
                f"review_global={global_review_cases} best={cleaned_len} elapsed={elapsed:.1f}s"
            )
            emit_event(
                self.event_sink,
                EventType.RUN_FINISHED,
                run_id=run_id,
                **_with_selection_limit(
                    {
                        "status": "completed",
                        "processed": ok_count + fail_count,
                        "errors": fail_count,
                        "duplicates": discovery.duplicate_count,
                        "review_cases": review_cases,
                        "global_review_cases": global_review_cases,
                        "clean_snapshot": cleaned_len,
                        "elapsed_s": elapsed,
                    },
                    options,
                ),
            )
            return "completed"
        except RunCancelled:
            log.warning("Run cancelled by user after current safe checkpoint.")
            reconcile = getattr(database, "reconcile_interrupted_run", None)
            if callable(reconcile):
                reconcile(
                    run_id,
                    status=RunStatus.CANCELLED,
                    error="cancelled_by_user",
                )
            else:
                database.complete_run(
                    run_id,
                    status=RunStatus.CANCELLED,
                    metrics={"operational_error_message": "cancelled_by_user"},
                )
            emit_event(
                self.event_sink,
                EventType.RUN_FINISHED,
                run_id=run_id,
                **_with_selection_limit(
                    {"status": "cancelled"},
                    options,
                ),
            )
            return "cancelled"
        finally:
            # No owned snapshot resources are opened in the runtime path.
            pass

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _log_discovery_preview(self, log, discovery, new_images) -> None:
        for duplicate in discovery.duplicates:
            if duplicate.reason == "batch":
                log.info(
                    f"  duplicate (batch): {duplicate.path.name} "
                    f"matches {duplicate.canonical_name}"
                )
            else:
                log.info(f"  duplicate (cached): {duplicate.path.name}")
        for path, file_hash in new_images:
            log.info(f"  process: {path.name}")
            log.debug(f"  process: {path.name}  hash={file_hash}")
        for existing in discovery.existing_images:
            log.info(f"  existing: {existing.path.name}")
        for skipped in discovery.skipped_images:
            log.info(f"  skipped ({skipped.reason}): {skipped.path.name}")
        log.info(f"Would process {len(new_images)} image(s)")

    def _retry_error_discovery(
        self,
        database,
        all_images,
        log,
    ) -> tuple[ImageDiscoveryPlan, list[tuple[Path, str]]]:
        available_by_path = {path.resolve(): path for path in all_images}
        retry_images: list[tuple[Path, str]] = []
        skipped_images: list[SkippedImage] = []
        skipped_missing = 0
        skipped_outside_input = 0

        for path, file_hash in database.list_failed_images_for_retry():
            if not path.exists():
                skipped_missing += 1
                skipped_images.append(SkippedImage(path=path, reason="retry_missing", file_hash=file_hash))
                continue
            resolved = path.resolve()
            if resolved not in available_by_path:
                skipped_outside_input += 1
                skipped_images.append(
                    SkippedImage(path=path, reason="retry_outside_selection", file_hash=file_hash)
                )
                continue
            retry_images.append((available_by_path[resolved], file_hash))

        if skipped_missing:
            log.warning(f"[retry-errors] skipped {skipped_missing} failed image(s) whose file is missing")
        if skipped_outside_input:
            log.warning(
                f"[retry-errors] skipped {skipped_outside_input} failed image(s) outside input_dir"
            )
        log.info(f"[retry-errors] {len(retry_images)} failed image(s) available for retry")

        discovery = ImageDiscoveryPlan(
            total=len(retry_images) + len(skipped_images),
            new_images=[
                DiscoveredImage(path=path, file_hash=file_hash)
                for path, file_hash in retry_images
            ],
            duplicates=[],
            existing_images=[],
            skipped_images=skipped_images,
        )
        return discovery, retry_images

    def _preflight_lmstudio(self, cfg, log, run_id: str, database) -> bool:
        context = _lmstudio_preflight_context(cfg)
        try:
            log.info(
                "[lmstudio] Preflight: ensuring model is loaded before processing "
                f"({context.model})"
            )
            with build_backend(cfg):
                pass
            self._record_lmstudio_runtime_snapshot(
                cfg,
                database,
                run_id=run_id,
                context=context,
            )
            return True
        except Exception as exc:
            message = (
                "lmstudio_preflight_failed: "
                f"model={context.model} endpoint={context.endpoint} error={exc}"
            )
            log.error(message)
            try:
                self._record_lmstudio_runtime_snapshot(
                    cfg,
                    database,
                    run_id=run_id,
                    context=context,
                )
            except Exception:
                log.debug("[lmstudio] Could not persist failed preflight snapshot")
            fail_preflight = getattr(database, "fail_preflight_run", None)
            if callable(fail_preflight):
                fail_preflight(run_id, error=message)
            else:
                database.fail_run(run_id, error=message)
            emit_event(
                self.event_sink,
                EventType.RUN_FINISHED,
                run_id=run_id,
                status="failed",
                error=message,
            )
            return False

    def _record_lmstudio_runtime_snapshot(
        self,
        cfg,
        database,
        *,
        run_id: str,
        context: _LMStudioPreflightContext,
    ) -> None:
        if not hasattr(database, "record_runtime_snapshot"):
            return
        client = LMStudioRuntimeClient(
            context.endpoint,
            timeout=getattr(cfg.llm, "timeout_connect", 5),
        )
        try:
            diagnostic = client.runtime_status(
                configured_model=context.model,
                desired_load_config=context.desired_load_config,
                reasoning_mode=getattr(cfg.llm, "reasoning_mode", None),
            )
            database.record_runtime_snapshot(run_id=run_id, diagnostic=diagnostic)
        finally:
            client.close()

    def _extraction(self, database: DatabaseService) -> ExtractionService:
        return self.extraction_service or ExtractionService(
            database_service=database,
            event_sink=self.event_sink,
            run_control=self.run_control,
        )

    def _rebuild(self, database: DatabaseService) -> RebuildService:
        return self.rebuild_service or RebuildService(
            database_service=database,
            event_sink=self.event_sink,
        )

    def make_run_id(self) -> str:
        """Generate a collision-safe run identifier.

        Format: YYYYMMDD_HHMMSS_<8-hex> — UTC date prefix with a UUID suffix
        that prevents collisions when two runs start in the same second.
        """
        prefix = utc_now().strftime("%Y%m%d_%H%M%S")
        return f"{prefix}_{uuid4().hex[:8]}"

    def _checkpoint(self) -> None:
        if self.run_control is not None:
            self.run_control.checkpoint()

    def _elapsed_since(self, started_at: float) -> float:
        if self.run_control is not None:
            return self.run_control.elapsed_since(started_at)
        return max(0.0, time.monotonic() - started_at)


def _execution_mode(workers: int) -> str:
    return "Sequential" if workers <= 1 else f"Parallel ({workers} workers)"


def _lmstudio_preflight_context(cfg) -> _LMStudioPreflightContext:
    llm = cfg.llm
    return _LMStudioPreflightContext(
        model=getattr(llm, "model", ""),
        endpoint=getattr(llm, "url", ""),
        desired_load_config={
            "context_length": getattr(llm, "context_length", None),
            "eval_batch_size": getattr(llm, "eval_batch_size", None),
            "physical_batch_size": getattr(llm, "physical_batch_size", None),
            "flash_attention": getattr(llm, "flash_attention", None),
            "offload_kv_cache_to_gpu": getattr(llm, "offload_kv_cache_to_gpu", None),
        },
    )


def _run_mode(options: RunOptions) -> str:
    return RunMode.DRY_RUN.value if options.dry_run else RunMode.NORMAL.value


def _selection_config(options: RunOptions) -> dict[str, object]:
    config: dict[str, object] = {}
    if options.max_images is not None:
        config["selection_limit"] = options.max_images
    if options.selected_image_file_ids:
        config["selected_image_file_ids"] = list(options.selected_image_file_ids)
    if options.force:
        config["force"] = True
    if options.retry_errors:
        config["retry_errors"] = True
    return config


def _begin_run_kwargs(cfg, run_id: str, options: RunOptions) -> dict:
    llm = getattr(cfg, "llm", None)
    image = getattr(cfg, "image", None)
    kwargs = {
        "run_id": run_id,
        "backend": LMSTUDIO_BACKEND_NAME,
        "model": cfg.llm.model,
        "prompt_name": cfg.prompt.active,
        "input_dir": str(cfg.input_dir),
        "workers": getattr(cfg, "workers", 1),
    }
    optional_values = {
        "image_format": getattr(llm, "image_format", None),
        "max_width": getattr(image, "max_width", None),
        "encode_quality": getattr(image, "encode_quality", None),
        "grayscale": getattr(image, "grayscale", None),
        "context_length": getattr(llm, "context_length", None),
        "reasoning_mode": getattr(llm, "reasoning_mode", None),
        "eval_batch_size": getattr(llm, "eval_batch_size", None),
        "physical_batch_size": getattr(llm, "physical_batch_size", None),
        "flash_attention": getattr(llm, "flash_attention", None),
        "offload_kv_cache_to_gpu": getattr(llm, "offload_kv_cache_to_gpu", None),
        "max_completion_tokens": getattr(llm, "max_completion_tokens", None),
        "temperature": getattr(llm, "temperature", None),
        "max_retries": getattr(llm, "max_retries", None),
        "timeout_connect": getattr(llm, "timeout_connect", None),
        "timeout_read": getattr(llm, "timeout_read", None),
        "performance_tps_floor": getattr(llm, "performance_tps_floor", None),
        "performance_reload_elapsed_s": getattr(llm, "performance_reload_elapsed_s", None),
        "performance_reload_streak": getattr(llm, "performance_reload_streak", None),
    }
    kwargs.update({key: value for key, value in optional_values.items() if value is not None})
    mode = _run_mode(options)
    if mode != RunMode.NORMAL.value:
        kwargs["mode"] = mode
    selection_config = _selection_config(options)
    if selection_config:
        kwargs["config"] = selection_config
    return kwargs


def _limit_discovery_processable(
    discovery: ImageDiscoveryPlan,
    max_images: int | None,
    log,
    *,
    label: str,
) -> ImageDiscoveryPlan:
    if max_images is None:
        return discovery

    selected = discovery.new_images[:max_images]
    excluded = discovery.new_images[max_images:]
    log.info(
        f"[selection] limited run to first {len(selected)} of "
        f"{len(discovery.new_images)} {label}(s)"
    )
    if not excluded:
        return discovery

    skipped = list(discovery.skipped_images)
    skipped.extend(
        SkippedImage(
            path=item.path,
            reason="selection_excluded",
            file_hash=item.file_hash,
        )
        for item in excluded
    )
    return ImageDiscoveryPlan(
        total=discovery.total,
        new_images=selected,
        duplicates=discovery.duplicates,
        existing_images=discovery.existing_images,
        skipped_images=skipped,
    )


def _with_selection_limit(payload: dict, options: RunOptions) -> dict:
    if options.max_images is None:
        return payload
    return {**payload, "selection_limit": options.max_images}


def _selection_payload(
    *,
    selection_limit: int | None,
    input_total: int,
    selected_count: int | None = None,
    **payload,
) -> dict:
    result = dict(payload)
    if selection_limit is not None or selected_count is not None:
        result["input_total"] = input_total
    if selection_limit is not None:
        result["selection_limit"] = selection_limit
    if selected_count is not None:
        result["selected_image_file_count"] = selected_count
    return result


def _selected_files(database, options: RunOptions) -> list[tuple[Path, str]] | None:
    if not options.selected_image_file_ids:
        return None
    selected = getattr(database, "selected_image_files", None)
    if not callable(selected):
        return []
    return selected(options.selected_image_file_ids)


def _mtime_sort_key(path: Path) -> tuple[float, str]:
    try:
        return path.stat().st_mtime, str(path).casefold()
    except OSError:
        return float("inf"), str(path).casefold()


def _account_for_unselected_files(
    discovery: ImageDiscoveryPlan,
    *,
    all_files: list[Path],
    selected_images: list[Path],
) -> ImageDiscoveryPlan:
    selected = {path.resolve() for path in selected_images}
    already_skipped = {item.path.resolve() for item in discovery.skipped_images}
    skipped = list(discovery.skipped_images)
    for path in all_files:
        resolved = path.resolve()
        if resolved in selected or resolved in already_skipped:
            continue
        reason = (
            "unsupported_extension"
            if path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS
            else "selection_excluded"
        )
        skipped.append(SkippedImage(path=path, reason=reason))
    return ImageDiscoveryPlan(
        total=(
            len(discovery.new_images)
            + len(discovery.duplicates)
            + len(discovery.existing_images)
            + len(skipped)
        ),
        new_images=discovery.new_images,
        duplicates=discovery.duplicates,
        existing_images=discovery.existing_images,
        skipped_images=skipped,
    )
