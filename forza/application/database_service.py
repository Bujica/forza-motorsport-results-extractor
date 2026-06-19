from __future__ import annotations

from pathlib import Path

from ..schemas import (
    ExportLap,
    ExternalLapRecord,
    ExtractionResult,
    ImageMetadata,
    ModelExtractionAttempt,
    ReviewCase,
    RunStatus,
)
from .db_session_provider import DbSessionProvider, DbStatus
from .best_lap_recompute_service import BestLapRecomputeService
from .extraction_persistence_service import (
    ExtractionPersistenceService,
    PreparedExtraction,
)
from .export_service import ExportArtifactService, ExportReadService
from .external_record_service import (
    ExternalRecordPersistenceService,
    ExternalRecordReadService,
)
from .reference_data_service import ReferenceDataService
from .image_service import (
    ImageDiscoveryInputService,
    ImageInventoryReadService,
    ImageRetryRegistrationService,
)
from .run_lifecycle_service import RunLifecycleService
from .runtime_snapshot_service import RuntimeSnapshotService
from .review_service import ReviewService
from .rebuild_service import RebuildService


class DatabaseService:
    """Compatibility facade for database-backed application services."""

    def __init__(self, database_file: Path, *, auto_upgrade: bool = False):
        self.database_file = database_file
        self.auto_upgrade = auto_upgrade
        self._session_provider = DbSessionProvider(database_file, auto_upgrade=auto_upgrade)
        self._run_lifecycle = RunLifecycleService(self._session_provider)
        self._runtime_snapshots = RuntimeSnapshotService(self._session_provider)
        self._extraction_persistence = ExtractionPersistenceService(self._session_provider)
        self._export_reads = ExportReadService(self._session_provider, database_file)
        self._export_artifacts = ExportArtifactService(self._session_provider)
        self._external_record_reads = ExternalRecordReadService(self._session_provider, database_file)
        self._external_record_persistence = ExternalRecordPersistenceService(self._session_provider)
        self._image_inventory = ImageInventoryReadService(self._session_provider)
        self._reference_data = ReferenceDataService(self._session_provider)
        self._image_discovery_inputs = ImageDiscoveryInputService(self._session_provider)
        self._image_retry_registration = ImageRetryRegistrationService(self._session_provider, database_file)
        self._best_lap_recompute = BestLapRecomputeService(self._session_provider, database_file)
        self._review_service = ReviewService(self._session_provider, database_file)
        self._rebuild_service = RebuildService(
            session_provider=self._session_provider,
            review_service=self._review_service,
        )

    def close(self) -> None:
        self._session_provider.close()

    def __enter__(self) -> "DatabaseService":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def begin_run(
        self,
        *,
        run_id: str,
        backend: str,
        model: str,
        prompt_name: str,
        input_dir: str,
        mode: str = "normal",
        config: dict | None = None,
        workers: int | None = None,
        image_format: str | None = None,
        max_width: int | None = None,
        encode_quality: int | None = None,
        grayscale: bool | None = None,
        context_length: int | None = None,
        reasoning_mode: str | None = None,
        eval_batch_size: int | None = None,
        physical_batch_size: int | None = None,
        flash_attention: bool | None = None,
        offload_kv_cache_to_gpu: bool | None = None,
        max_completion_tokens: int | None = None,
        temperature: float | None = None,
        max_retries: int | None = None,
        timeout_connect: int | None = None,
        timeout_read: int | None = None,
        performance_tps_floor: float | None = None,
        performance_reload_elapsed_s: float | None = None,
        performance_reload_streak: int | None = None,
    ) -> None:
        self._run_lifecycle.begin_run(
            run_id=run_id,
            backend=backend,
            model=model,
            prompt_name=prompt_name,
            input_dir=input_dir,
            mode=mode,
            config=config,
            workers=workers,
            image_format=image_format,
            max_width=max_width,
            encode_quality=encode_quality,
            grayscale=grayscale,
            context_length=context_length,
            reasoning_mode=reasoning_mode,
            eval_batch_size=eval_batch_size,
            physical_batch_size=physical_batch_size,
            flash_attention=flash_attention,
            offload_kv_cache_to_gpu=offload_kv_cache_to_gpu,
            max_completion_tokens=max_completion_tokens,
            temperature=temperature,
            max_retries=max_retries,
            timeout_connect=timeout_connect,
            timeout_read=timeout_read,
            performance_tps_floor=performance_tps_floor,
            performance_reload_elapsed_s=performance_reload_elapsed_s,
            performance_reload_streak=performance_reload_streak,
        )

    def record_runtime_snapshot(
        self,
        *,
        run_id: str,
        diagnostic,
        snapshot_kind: str = "preflight",
    ) -> str:
        return self._runtime_snapshots.record_runtime_snapshot(
            run_id=run_id,
            diagnostic=diagnostic,
            snapshot_kind=snapshot_kind,
        )

    def complete_run(self, run_id: str, *, metrics: dict | None = None, status: RunStatus | str = RunStatus.COMPLETED) -> None:
        self._run_lifecycle.complete_run(run_id, metrics=metrics, status=status)

    def fail_run(self, run_id: str, *, error: str, error_code: str | None = None) -> None:
        self._run_lifecycle.fail_run(run_id, error=error, error_code=error_code)

    def fail_preflight_run(self, run_id: str, *, error: str) -> None:
        self._run_lifecycle.fail_preflight_run(run_id, error=error)

    def prepare_extraction_result(
        self,
        *,
        run_id: str,
        file_hash: str,
        path: Path,
    ) -> PreparedExtraction:
        return self._extraction_persistence.prepare_extraction_result(
            run_id=run_id,
            file_hash=file_hash,
            path=path,
        )

    def record_extraction_attempt(
        self,
        *,
        prepared: PreparedExtraction,
        attempt: ModelExtractionAttempt,
        run_id: str,
    ) -> str:
        return self._extraction_persistence.record_extraction_attempt(
            prepared=prepared,
            attempt=attempt,
            run_id=run_id,
        )

    def reconcile_interrupted_run(
        self,
        run_id: str,
        *,
        status: RunStatus | str,
        error: str,
    ) -> None:
        self._run_lifecycle.reconcile_interrupted_run(
            run_id,
            status=status,
            error=error,
        )

    def image_inventory(self) -> tuple[set[str], dict[str, str]]:
        return self._image_inventory.image_inventory()

    def selected_image_files(self, image_file_ids: list[str] | tuple[str, ...]) -> list[tuple[Path, str]]:
        return self._image_inventory.selected_image_files(image_file_ids)

    def record_discovery_inputs(
        self,
        *,
        run_id: str,
        discovery,
        process_reason: str = "full_run",
        dry_run: bool = False,
    ) -> None:
        self._image_discovery_inputs.record_discovery_inputs(
            run_id=run_id,
            discovery=discovery,
            process_reason=process_reason,
            dry_run=dry_run,
        )

    def list_failed_images_for_retry(self) -> list[tuple[Path, str]]:
        return self._image_retry_registration.list_failed_images_for_retry()

    def recompute_best_laps(self, *, run_id: str | None = None, gamertag: str | None = None) -> int:
        return self._best_lap_recompute.recompute_best_laps(run_id=run_id, gamertag=gamertag)

    def register_image_file(
        self,
        *,
        file_hash: str,
        path: Path,
        semantic_name: str | None = None,
        duplicate_of_hash: str | None = None,
        run_id: str | None = None,
        metadata: ImageMetadata | None = None,
    ) -> str:
        return self._image_retry_registration.register_image_file(
            file_hash=file_hash,
            path=path,
            semantic_name=semantic_name,
            duplicate_of_hash=duplicate_of_hash,
            run_id=run_id,
            metadata=metadata,
        )

    def latest_completed_run_id(self) -> str | None:
        return self._run_lifecycle.latest_completed_run_id()

    def list_full_flat(self, *, run_id: str | None = None) -> list[ExportLap]:
        return self._export_reads.list_full_flat(run_id=run_id)

    def list_clean_flat(self, *, run_id: str | None = None) -> list[ExportLap]:
        return self._export_reads.list_clean_flat(run_id=run_id)

    def upsert_image_and_laps(
        self,
        result: ExtractionResult,
        *,
        run_id: str,
        gamertag: str | None = None,
    ) -> int:
        return self._extraction_persistence.upsert_image_and_laps(
            result,
            run_id=run_id,
            gamertag=gamertag,
        )

    def refresh_review_cases(self, *, run_id: str | None = None) -> tuple[int, int, int]:
        return self._review_service.refresh_review_cases(run_id=run_id)

    def rebuild_derived_state(self, *, gamertag: str | None = None) -> tuple[int, tuple[int, int, int]]:
        return self._rebuild_service.rebuild_derived_state(gamertag=gamertag)

    def list_open_review_cases(self) -> list[ReviewCase]:
        return self._review_service.list_open_review_cases()

    def count_lap_records(self) -> int:
        return self._best_lap_recompute.count_lap_records()

    def count_best_laps(self) -> int:
        return self._best_lap_recompute.count_best_laps()

    def count_review_cases(
        self,
        *,
        run_id: str | None = None,
        status: str | None = None,
    ) -> int:
        return self._review_service.count_review_cases(run_id=run_id, status=status)

    def seed_references(self, *, tracks: list[str], cars: list[str]) -> tuple[int, int]:
        return self._reference_data.seed_references(tracks=tracks, cars=cars)

    def list_reference_tracks(self) -> list[str]:
        return self._reference_data.list_reference_tracks()

    def list_reference_cars(self) -> list[str]:
        return self._reference_data.list_reference_cars()

    def load_reference_data(self):
        return self._reference_data.load_reference_data()

    def replace_external_records(
        self,
        records: list[ExternalLapRecord],
        *,
        source_path: Path | str,
        source_hash: str | None = None,
        total_rows: int | None = None,
        issues: list[dict] | None = None,
        rejected_rows: int | None = None,
    ) -> int:
        return self._external_record_persistence.replace_external_records(
            records,
            source_path=source_path,
            source_hash=source_hash,
            total_rows=total_rows,
            issues=issues,
            rejected_rows=rejected_rows,
        )

    def list_external_records(self) -> list[ExternalLapRecord]:
        return self._external_record_reads.list_external_records()

    def record_artifact(self, *, path: Path | str, format: str, run_id: str | None = None) -> None:
        self._export_artifacts.record_artifact(path=path, format=format, run_id=run_id)

    def status(self) -> DbStatus:
        return self._session_provider.status()

    def status_for_config(self, cfg) -> DbStatus:
        return self._session_provider.status_for_config(cfg)

    def reconcile_abandoned_runs(self) -> int:
        return self._run_lifecycle.reconcile_abandoned_runs()

    def _engine_for_db(self):
        """Compatibility seam for tests and low-level DB diagnostics."""

        return self._session_provider.engine_for_db()

