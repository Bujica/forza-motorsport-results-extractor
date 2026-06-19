from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

from ...config import AppConfig
from ...events import EventType, PipelineEvent
from ...application.gui_read_service import GuiImage, GuiReadService
from ...application.gui_write_service import GuiWriteService
from ...application import ImageRenameService, RenamePlan
from ...pipeline import file_hash
from ..config_state import ConfigChangeSet
from ..workers.image_inventory_worker import ImageInventoryWorker, ImageInventoryWorkerResult


@dataclass(frozen=True)
class ImageActionResult:
    ok: bool
    message: str


@dataclass(frozen=True)
class RenamePlanSummary:
    total: int
    would_change: int
    missing: int
    plans: list[RenamePlan]


@dataclass(frozen=True)
class ImageFilterOptions:
    tracks: list[str]
    runs: list[object]


class ImageController(QObject):
    images_changed = Signal(object)
    filter_options_changed = Signal(object)
    selection_detail_changed = Signal(object, object)
    action_completed = Signal(str)
    action_failed = Signal(str)
    scan_running_changed = Signal(bool)

    def __init__(self, *, cfg: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._reader = GuiReadService(cfg.database_file)
        self._writer = GuiWriteService(cfg.database_file)
        self._renamer = ImageRenameService(cfg.database_file)
        self._images: list[GuiImage] = []
        self._file_status: str | None = None
        self._best_lap_status: str | None = None
        self._inventory_filter: str | None = None
        self._track: str | None = None
        self._run_id: str | None = None
        self._processing_status: str | None = None
        self._scan_thread: QThread | None = None
        self._scan_worker: ImageInventoryWorker | None = None
        self._scan_announce = False
        self._scan_pending = False

    @property
    def images(self) -> list[GuiImage]:
        return list(self._images)

    @property
    def is_scanning(self) -> bool:
        return self._scan_thread is not None and self._scan_thread.isRunning()

    def on_config_changed(self, cfg: AppConfig, changes: ConfigChangeSet) -> None:
        self._cfg = cfg
        if not changes.affects("paths.database_file"):
            return
        self._reader.close()
        self._writer.close()
        self._reader = GuiReadService(cfg.database_file)
        self._writer = GuiWriteService(cfg.database_file)
        self._renamer = ImageRenameService(cfg.database_file)
        self._images = []
        self.images_changed.emit(self._images)
        self.filter_options_changed.emit(ImageFilterOptions([], []))
        self.selection_detail_changed.emit([], None)

    def close(self) -> None:
        self._reader.close()
        self._writer.close()
        if self._scan_thread is not None and self._scan_thread.isRunning():
            self._scan_thread.quit()
            if not self._scan_thread.wait(5000):
                self._scan_thread.terminate()
                self._scan_thread.wait(1000)

    def refresh(
        self,
        file_status: str | None = None,
        best_lap_status: str | None = None,
        inventory_filter: str | None = None,
        track: str | None = None,
        run_id: str | None = None,
        processing_status: str | None = None,
    ) -> None:
        self._file_status = _none_for_all(file_status)
        self._best_lap_status = _none_for_all(best_lap_status)
        self._inventory_filter = _none_for_all(inventory_filter)
        self._track = _none_for_all(track)
        self._run_id = _none_for_all(run_id)
        self._processing_status = _none_for_all(processing_status)
        self._images = self._reader.list_images(
            file_status=self._file_status,
            best_lap_status=self._best_lap_status,
            inventory_filter=self._inventory_filter,
            track=self._track,
            run_id=self._run_id,
            processing_status=self._processing_status,
        )
        self.images_changed.emit(self._images)
        self.filter_options_changed.emit(self._filter_options())

    def scan_input_folder(self) -> ImageActionResult:
        return self._start_input_folder_scan(announce=True)

    def sync_input_folder(self) -> ImageActionResult:
        return self._start_input_folder_scan(announce=False)

    def _start_input_folder_scan(self, *, announce: bool) -> ImageActionResult:
        if self.is_scanning:
            self._scan_pending = True
            message = "Input folder sync is already running."
            if announce:
                self.action_failed.emit(message)
            return ImageActionResult(False, message)

        self._scan_announce = announce
        self._scan_thread = QThread(self)
        self._scan_worker = ImageInventoryWorker(
            database_file=self._cfg.database_file,
            input_dir=self._cfg.input_dir,
        )
        self._scan_worker.moveToThread(self._scan_thread)

        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.finished.connect(self._on_input_folder_scan_finished)
        self._scan_worker.finished.connect(self._scan_thread.quit)
        self._scan_worker.finished.connect(self._scan_worker.deleteLater)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)
        self._scan_thread.finished.connect(self._clear_scan_worker_refs)

        self.scan_running_changed.emit(True)
        self._scan_thread.start()
        return ImageActionResult(True, "Input folder sync started.")

    def _on_input_folder_scan_finished(self, result: ImageInventoryWorkerResult) -> None:
        announce = self._scan_announce
        if result.ok and result.scan_result is not None:
            self.refresh(
                self._file_status,
                self._best_lap_status,
                self._inventory_filter,
                self._track,
                self._run_id,
                self._processing_status,
            )
            message = _scan_result_message(result.scan_result)
            if announce:
                self.action_completed.emit(message)
            return

        message = f"Input folder scan failed: {result.message or 'unknown error'}"
        self.action_failed.emit(message)

    def _clear_scan_worker_refs(self) -> None:
        self._scan_thread = None
        self._scan_worker = None
        self.scan_running_changed.emit(False)
        if self._scan_pending:
            self._scan_pending = False
            self._start_input_folder_scan(announce=False)

    def select_images(self, image_ids: list[str]) -> None:
        selected = [image for image in self._images if image.id in set(image_ids)]
        self.selection_detail_changed.emit(selected, selected[0] if len(selected) == 1 else None)

    def plan_rename(self, image_ids: list[str]) -> RenamePlanSummary:
        plans = self._renamer.plan_rename_many(image_ids)
        planned_ids = {plan.image_file_id for plan in plans}
        missing = len([image_id for image_id in image_ids if image_id not in planned_ids])
        return RenamePlanSummary(
            total=len(image_ids),
            would_change=sum(1 for plan in plans if plan.would_change),
            missing=missing,
            plans=plans,
        )

    def rename_images(self, image_ids: list[str]) -> ImageActionResult:
        renamed = 0
        errors: list[str] = []
        for result in self._renamer.rename_files(image_ids, dry_run=False):
            if result.renamed:
                renamed += 1
            if result.error:
                errors.append(f"{result.plan.image_file_id}: {result.error}")
        self.refresh(self._file_status, self._best_lap_status, self._inventory_filter, self._track, self._run_id, self._processing_status)
        if errors:
            message = f"Renamed: {renamed}; errors: {len(errors)}"
            self.action_failed.emit(message)
            return ImageActionResult(False, message)
        message = f"Renamed: {renamed}"
        self.action_completed.emit(message)
        return ImageActionResult(True, message)

    def export_images(self, image_ids: list[str], destination: Path) -> ImageActionResult:
        result = self._renamer.export_images(image_ids, destination, naming="semantic")
        message = f"Copied: {result.copied}; skipped: {result.skipped}; destination: {result.destination}"
        self.action_completed.emit(message)
        return ImageActionResult(True, message)

    def delete_images(self, image_ids: list[str]) -> ImageActionResult:
        selected = [image for image in self._images if image.id in set(image_ids)]
        files_deleted = 0
        records_deleted = 0
        already_missing = 0
        skipped = 0
        errors: list[str] = []
        for image in selected:
            path = self._resolved_image_path(image)
            if path is None and image.current_path:
                errors.append(f"{image.current_name or image.id}: path is outside the configured input folder")
                skipped += 1
                continue
            try:
                if path is not None and path.exists() and path.is_file():
                    path.unlink()
                    files_deleted += 1
                elif path is not None:
                    already_missing += 1
                if self._writer.delete_image_file(image.id):
                    records_deleted += 1
            except OSError as exc:
                errors.append(f"{image.current_name or image.id}: {exc}")
        self.refresh(self._file_status, self._best_lap_status, self._inventory_filter, self._track, self._run_id, self._processing_status)
        message = f"Deleted files: {files_deleted}; database records: {records_deleted}; already missing: {already_missing}; skipped: {skipped}"
        if errors:
            message = f"{message}; errors: {len(errors)}"
            self.action_failed.emit(message)
            return ImageActionResult(False, message)
        self.action_completed.emit(message)
        return ImageActionResult(True, message)

    def rescan_images(self, image_ids: list[str]) -> ImageActionResult:
        selected = [image for image in self._images if image.id in set(image_ids)]
        available = 0
        missing = 0
        changed = 0
        hash_changed = 0
        skipped = 0
        for image in selected:
            path = self._resolved_image_path(image)
            if path is None:
                skipped += 1
                continue
            next_status = "missing"
            if path.exists() and path.is_file():
                try:
                    current_hash = file_hash(path)
                except OSError:
                    skipped += 1
                    continue
                if current_hash != image.file_hash:
                    hash_changed += 1
                    continue
                next_status = "available"
            if next_status == "available":
                available += 1
            else:
                missing += 1
            if image.file_status != next_status and self._writer.set_file_status(image.id, next_status) is not None:
                changed += 1
        self.refresh(self._file_status, self._best_lap_status, self._inventory_filter, self._track, self._run_id, self._processing_status)
        message = (
            f"Rescanned: {len(selected)}; available: {available}; missing: {missing}; "
            f"changed: {changed}; hash changed: {hash_changed}; skipped: {skipped}"
        )
        self.action_completed.emit(message)
        return ImageActionResult(True, message)

    def _resolved_image_path(self, image: GuiImage) -> Path | None:
        if image.current_path is None:
            return None
        path = Path(image.current_path)
        candidate = path if path.is_absolute() else Path.cwd() / path
        resolved = candidate.resolve()
        allowed_roots = [
            self._resolve_root(self._cfg.input_dir),
        ]
        if not any(_is_within(resolved, root) for root in allowed_roots):
            return None
        return resolved

    def _resolve_root(self, path: Path) -> Path:
        root = Path(path)
        return (root if root.is_absolute() else Path.cwd() / root).resolve()

    def handle_event(self, event: PipelineEvent) -> None:
        if event.type in {EventType.IMAGE_STATUS_CHANGED, EventType.IMAGE_RENAMED, EventType.IMAGE_EXPORTED, EventType.RUN_FINISHED}:
            self.refresh(self._file_status, self._best_lap_status, self._inventory_filter, self._track, self._run_id, self._processing_status)

    def _filter_options(self) -> ImageFilterOptions:
        tracks, runs = self._reader.image_filter_values(
            file_status=self._file_status,
            best_lap_status=self._best_lap_status,
            inventory_filter=self._inventory_filter,
            track=self._track,
            run_id=self._run_id,
            processing_status=self._processing_status,
        )
        return ImageFilterOptions(tracks=tracks, runs=runs)


def _scan_result_message(result) -> str:
    return (
        f"Scanned: {result.total_files}; registered: {result.registered}; "
        f"refreshed: {result.refreshed}; missing: {result.missing}; skipped: {result.skipped}"
    )


def _none_for_all(value: str | None) -> str | None:
    if value in (None, "", "all"):
        return None
    return value


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
