from __future__ import annotations
import logging

import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlmodel import Session, select

from ..db import create_sqlite_engine
from ..db.migrate import require_db_ready
from ..db.models import ExtractionResultEntity, ExtractionRunEntity, RunInputEntity, ImageFileEntity, ImageFlagEntity
from ..pipeline import ImageDiscoveryPlan, file_hash, find_images, inspect_image_metadata, log_duplicate_skips, plan_images
from ..db.repositories import ImageFlagRepository, ImageFileRepository
from ..schemas import ImageMetadata
from .db_session_provider import DbSessionProvider

_WIN_FORBIDDEN = set('<>:"/\\|?*')
_WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

_log = logging.getLogger("forza")


@dataclass(frozen=True)
class RenamePlan:
    image_file_id: str
    source_path: Path
    target_path: Path
    semantic_name: str
    would_change: bool
    reason: str = ""


@dataclass(frozen=True)
class RenameResult:
    plan: RenamePlan
    renamed: bool
    error: str | None = None


@dataclass(frozen=True)
class ExportImagesResult:
    destination: Path
    copied: int
    skipped: int
    files: list[Path]


@dataclass(frozen=True)
class ImageInventoryResult:
    plan: ImageDiscoveryPlan
    new_count: int
    existing_count: int
    duplicate_count: int


@dataclass(frozen=True)
class InputFolderScanResult:
    total_files: int
    registered: int
    refreshed: int
    missing: int
    skipped: int



class ImageInventoryReadService:
    """Owns database-backed image file inventory reads."""

    def __init__(self, session_provider: DbSessionProvider):
        self._session_provider = session_provider

    def image_inventory(self) -> tuple[set[str], dict[str, str]]:
        with Session(self._session_provider.engine_for_db()) as session:
            rows = session.exec(
                select(ImageFileEntity.file_hash, ImageFileEntity.current_path)
            ).all()
            return (
                {file_hash for file_hash, _path in rows if file_hash},
                {
                    current_path: file_hash
                    for file_hash, current_path in rows
                    if file_hash and current_path
                },
            )

    def selected_image_files(self, image_file_ids: list[str] | tuple[str, ...]) -> list[tuple[Path, str]]:
        if not image_file_ids:
            return []
        requested = list(dict.fromkeys(str(image_id) for image_id in image_file_ids if image_id))
        with Session(self._session_provider.engine_for_db()) as session:
            rows = session.exec(
                select(ImageFileEntity).where(ImageFileEntity.id.in_(requested))
            ).all()
        by_id = {row.id: row for row in rows}
        selected: list[tuple[Path, str]] = []
        for image_id in requested:
            image = by_id.get(image_id)
            if image is None or image.file_status != "available" or not image.current_path:
                continue
            path = Path(image.current_path)
            if not path.exists():
                continue
            selected.append((path, image.file_hash))
        return selected


class ImageDiscoveryInputService:
    """Owns discovery input persistence for extraction runs."""

    def __init__(self, session_provider: DbSessionProvider):
        self._session_provider = session_provider

    def record_discovery_inputs(
        self,
        *,
        run_id: str,
        discovery,
        process_reason: str = "full_run",
        dry_run: bool = False,
    ) -> None:
        rows: list[tuple[Path, str, str, str | None, str | None, str | None, str | None]] = []
        for item in discovery.new_images:
            rows.append((item.path, item.file_hash, "process", process_reason, None, None, None))
        for item in discovery.existing_images:
            rows.append((item.path, item.file_hash, "skip", None, "existing_ok", None, None))
        for item in discovery.duplicates:
            rows.append((
                item.path,
                item.file_hash,
                "duplicate",
                None,
                None,
                "batch" if item.reason == "batch" else "hash",
                item.duplicate_of_hash,
            ))
        for item in getattr(discovery, "skipped_images", []):
            decision, skip_reason = _skipped_input_contract(item.reason)
            rows.append((item.path, item.file_hash, decision, None, skip_reason, None, None))
        with Session(self._session_provider.engine_for_db()) as session:
            images = ImageFileRepository(session)
            input_by_hash: dict[str, int] = {}
            inserted_decisions: list[str] = []
            for input_order, (path, file_hash, decision, reason, skip_reason, duplicate_kind, duplicate_of_hash) in enumerate(rows):
                image_file_id = None
                if dry_run and decision == "process":
                    decision = "skip"
                    skip_reason = "dry_run"
                    reason = None
                if file_hash:
                    image = images.by_current_path(path)
                    if image is not None and image.file_hash != file_hash:
                        image = None
                    if image is None and decision == "process":
                        image = images.upsert(
                            file_hash=file_hash,
                            file_name=path.name,
                            current_path=path,
                            current_name=path.name,
                        )
                        session.flush()
                    elif image is None and duplicate_of_hash:
                        canonical = images.by_hash(duplicate_of_hash)
                        image = images.upsert(
                            file_hash=file_hash,
                            file_name=path.name,
                            current_path=path,
                            current_name=path.name,
                            duplicate_of_image_file_id=(
                                canonical.id if canonical is not None else None
                            ),
                        )
                        session.flush()
                    image_file_id = image.id if image is not None else None
                normalized_path, size_bytes, mtime_ns = _input_file_snapshot(path)
                row = RunInputEntity(
                    run_id=run_id,
                    image_file_id=image_file_id,
                    input_order=input_order,
                    input_path=str(path),
                    normalized_path=normalized_path,
                    file_name=path.name,
                    extension=path.suffix.lower(),
                    file_hash=file_hash,
                    size_bytes=size_bytes,
                    mtime_ns=mtime_ns,
                    decision=decision,
                    process_reason=reason,
                    skip_reason=skip_reason,
                    duplicate_kind=duplicate_kind,
                    duplicate_of_hash=duplicate_of_hash,
                    duplicate_of_input_id=input_by_hash.get(duplicate_of_hash or ""),
                )
                session.add(row)
                session.flush()
                if row.id is not None and file_hash and file_hash not in input_by_hash:
                    input_by_hash[file_hash] = row.id
                inserted_decisions.append(decision)
            run = session.get(ExtractionRunEntity, run_id)
            if run is not None:
                run.total_inputs = len(inserted_decisions)
                run.to_process = inserted_decisions.count("process")
                run.skipped = sum(
                    1 for decision in inserted_decisions
                    if decision not in {"process", "duplicate"}
                )
                run.duplicate_count = inserted_decisions.count("duplicate")
                session.add(run)
            session.commit()


def _skipped_input_contract(reason: str) -> tuple[str, str | None]:
    decision = {
        "unsupported_extension": "unsupported",
        "hash_failed": "hash_failed",
        "retry_missing": "missing",
        "retry_outside_selection": "outside_input",
    }.get(reason, "skip")
    return decision, reason


def _input_file_snapshot(path: Path) -> tuple[str, int | None, int | None]:
    try:
        normalized_path = str(path.resolve())
    except OSError:
        normalized_path = str(path)
    try:
        stat = path.stat()
    except OSError:
        return normalized_path, None, None
    return normalized_path, stat.st_size, stat.st_mtime_ns


class ImageRetryRegistrationService:
    """Owns retry inventory reads and image file registration."""

    def __init__(self, session_provider: DbSessionProvider, database_file: Path):
        self._session_provider = session_provider
        self.database_file = Path(database_file)

    def list_failed_images_for_retry(self) -> list[tuple[Path, str]]:
        """Return available images whose latest extraction result is still error."""
        if not self.database_file.exists():
            return []
        with Session(self._session_provider.engine_for_db()) as session:
            rows = session.exec(
                select(ExtractionResultEntity, ImageFileEntity)
                .join(ImageFileEntity, ImageFileEntity.id == ExtractionResultEntity.image_file_id)
                .where(ImageFileEntity.file_status == "available")
                .order_by(ExtractionResultEntity.created_at.desc())
            ).all()

            seen: set[str] = set()
            failed: list[tuple[Path, str]] = []
            for result, image in rows:
                if result.image_file_id in seen:
                    continue
                seen.add(result.image_file_id)
                if result.status != "error":
                    continue
                failed.append((Path(image.current_path), image.file_hash))
            return failed

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
        metadata = metadata or self._inspect_metadata(path)
        with Session(self._session_provider.engine_for_db()) as session:
            images = ImageFileRepository(session)
            canonical = images.by_hash(duplicate_of_hash) if duplicate_of_hash else None
            image = images.upsert(
                file_hash=file_hash,
                file_name=path.name,
                current_path=path,
                current_name=path.name,
                semantic_name=semantic_name,
                duplicate_of_image_file_id=canonical.id if canonical is not None else None,
                best_lap_status=None,
                metadata=metadata,
            )
            if canonical is not None:
                session.flush()
                flags = ImageFlagRepository(session)
                if not flags.list_open(image_file_id=image.id, flag="duplicate"):
                    flags.add_flag(
                        image_file_id=image.id,
                        run_id=run_id,
                        flag="duplicate",
                        reason="duplicate_file_hash",
                    )
            session.commit()
            return image.id

    def _inspect_metadata(self, path: Path) -> ImageMetadata | None:
        try:
            return inspect_image_metadata(path)
        except Exception:
            _log.warning("[db] Could not inspect image metadata for %s", path, exc_info=True)
            return None


class ImageInventoryService:
    """Classify and register image files without mutating image files."""

    def __init__(self, database):
        self.database = database

    def classify(self, images: list[Path], *, force: bool = False) -> ImageInventoryResult:
        known_hashes, known_paths = self._processed_image_inventory()
        plan = plan_images(images, known_hashes, known_paths=known_paths, force=force)
        return ImageInventoryResult(
            plan=plan,
            new_count=plan.process_count,
            existing_count=len(plan.existing_images),
            duplicate_count=plan.duplicate_count,
        )

    def _processed_image_inventory(self) -> tuple[set[str], dict[str, str]]:
        """Return images that have final extraction evidence.

        ``image_files`` is physical file inventory, not processing cache. Dry-runs and
        discovery-only paths may create source rows without model results; those
        rows must not cause a later normal run to skip work. Images with final
        extraction results are cached for normal runs; failed images are retried
        explicitly through ``--retry-errors``.
        """
        database_file = getattr(self.database, "database_file", None)
        if database_file is None:
            return self.database.image_inventory()

        require_db_ready(database_file)
        engine = create_sqlite_engine(database_file)
        try:
            with Session(engine) as session:
                rows = session.exec(
                    select(ImageFileEntity.file_hash, ImageFileEntity.current_path)
                    .join(
                        ExtractionResultEntity,
                        ExtractionResultEntity.image_file_id == ImageFileEntity.id,
                    )
                    .where(ExtractionResultEntity.status.in_(["ok", "error"]))
                ).all()
        finally:
            engine.dispose()

        return (
            {file_hash for file_hash, _path in rows if file_hash},
            {current_path: file_hash for file_hash, current_path in rows if file_hash and current_path},
        )

    def register(self, result: ImageInventoryResult, *, run_id: str | None = None) -> None:
        for image in result.plan.new_images:
            self.database.register_image_file(file_hash=image.file_hash, path=image.path)

        skipped = log_duplicate_skips(result.plan)
        for duplicate in result.plan.duplicates:
            self.database.register_image_file(
                file_hash=duplicate.file_hash,
                path=duplicate.path,
                duplicate_of_hash=duplicate.duplicate_of_hash,
                run_id=run_id,
            )
        if skipped:
            import logging

            logging.getLogger("forza").info(
                "[image] Registered %s duplicate image occurrence(s) in SQLite",
                len(skipped),
            )

    def scan_input_folder(self, input_dir: Path) -> InputFolderScanResult:
        """Register physical input images without processing them through the model."""
        database_file = getattr(self.database, "database_file", None)
        if database_file is None:
            raise RuntimeError("scan_input_folder requires a database-backed service")

        require_db_ready(database_file)
        paths = find_images(Path(input_dir))
        engine = create_sqlite_engine(database_file)
        registered = 0
        refreshed = 0
        skipped = 0
        seen_paths: set[str] = set()
        touched_hashes: set[str] = set()
        try:
            with Session(engine) as session:
                repo = ImageFileRepository(session)
                flags = ImageFlagRepository(session)
                for path in paths:
                    try:
                        image_hash = file_hash(path)
                    except OSError:
                        skipped += 1
                        continue
                    touched_hashes.add(image_hash)
                    existing = repo.by_current_path(path)
                    try:
                        metadata = inspect_image_metadata(path)
                    except Exception:
                        _log.warning("[image] Could not inspect image metadata for %s", path, exc_info=True)
                        metadata = None
                    canonical = repo.by_hash(image_hash)
                    duplicate_of_image_file_id = (
                        canonical.id
                        if canonical is not None
                        and (existing is None or canonical.id != existing.id)
                        else None
                    )
                    image = repo.upsert(
                        file_hash=image_hash,
                        file_name=path.name,
                        current_path=path,
                        current_name=path.name,
                        duplicate_of_image_file_id=duplicate_of_image_file_id,
                        metadata=metadata,
                    )
                    if duplicate_of_image_file_id and not flags.list_open(image_file_id=image.id, flag="duplicate"):
                        flags.add_flag(
                            image_file_id=image.id,
                            flag="duplicate",
                            reason="duplicate_file_hash",
                        )
                    if existing is None:
                        registered += 1
                    else:
                        refreshed += 1
                    seen_paths.add(str(path))

                missing = 0
                missing_candidates = session.exec(
                    select(ImageFileEntity)
                    .where(ImageFileEntity.current_path.is_not(None))
                    .where(ImageFileEntity.file_status == "available")
                ).all()
                for image in missing_candidates:
                    if not image.current_path:
                        continue
                    path = Path(image.current_path)
                    if str(path) in seen_paths or path.exists():
                        continue
                    touched_hashes.add(image.file_hash)
                    if image.file_status != "missing":
                        missing += 1
                    image.file_status = "missing"
                    image.missing_at = datetime.now(timezone.utc)
                    image.updated_at = datetime.now(timezone.utc)
                    session.add(image)
                _reconcile_duplicate_hashes(session, flags, touched_hashes)
                session.commit()
        finally:
            engine.dispose()

        return InputFolderScanResult(
            total_files=len(paths),
            registered=registered,
            refreshed=refreshed,
            missing=missing,
            skipped=skipped,
        )


def _reconcile_duplicate_hashes(
    session: Session,
    flags: ImageFlagRepository,
    file_hashes: set[str],
) -> None:
    """Keep duplicate relationships anchored on available physical files.

    A missing row must not remain the canonical parent for an available image
    when the same bytes reappear at another path. Duplicate state is a
    property of simultaneously available physical files, so missing rows are
    detached and active duplicate flags are resolved.
    """
    for file_hash_value in sorted(value for value in file_hashes if value):
        rows = list(
            session.exec(
                select(ImageFileEntity)
                .where(ImageFileEntity.file_hash == file_hash_value)
                .order_by(ImageFileEntity.created_at.asc(), ImageFileEntity.id.asc())
            ).all()
        )
        if not rows:
            continue

        now = datetime.now(timezone.utc)
        available = [row for row in rows if row.file_status == "available"]
        canonical = available[0] if available else None
        for row in rows:
            next_duplicate_of = (
                canonical.id
                if canonical is not None
                and row.file_status == "available"
                and row.id != canonical.id
                else None
            )
            if row.duplicate_of_image_file_id != next_duplicate_of:
                row.duplicate_of_image_file_id = next_duplicate_of
                row.updated_at = now
                session.add(row)
            if next_duplicate_of is None:
                _resolve_active_duplicate_flags(session, row.id, now)
            else:
                _ensure_active_duplicate_flag(session, flags, row.id)


def _ensure_active_duplicate_flag(
    session: Session,
    flags: ImageFlagRepository,
    image_file_id: str,
) -> None:
    existing = session.exec(
        select(ImageFlagEntity).where(
            ImageFlagEntity.image_file_id == image_file_id,
            ImageFlagEntity.flag_type == "duplicate",
        )
    ).first()
    if existing is None:
        flags.add_flag(
            image_file_id=image_file_id,
            flag="duplicate",
            reason="duplicate_file_hash",
        )
        return
    if existing.status != "active":
        existing.status = "active"
        existing.resolved_at = None
    existing.reason = "duplicate_file_hash"
    session.add(existing)


def _resolve_active_duplicate_flags(
    session: Session,
    image_file_id: str,
    resolved_at: datetime,
) -> None:
    for flag in session.exec(
        select(ImageFlagEntity).where(
            ImageFlagEntity.image_file_id == image_file_id,
            ImageFlagEntity.flag_type == "duplicate",
            ImageFlagEntity.status == "active",
        )
    ).all():
        flag.status = "resolved"
        flag.resolved_at = resolved_at
        session.add(flag)


class ImageRenameService:
    """Explicit metadata-based image rename/export operations.

    Extraction never depends on these operations. They are user-facing actions
    for organizing files outside the internal processing contract.
    """

    def __init__(self, database_file: Path):
        self.database_file = Path(database_file)

    def build_semantic_name(self, image_file_id: str) -> str | None:
        image = self._get_image(image_file_id)
        if image is None:
            return None
        return self._preferred_name(image, naming="semantic")

    def plan_rename(self, image_file_id: str) -> RenamePlan | None:
        plans = self.plan_rename_many([image_file_id])
        return plans[0] if plans else None

    def plan_rename_many(self, image_file_ids: list[str]) -> list[RenamePlan]:
        images = self._get_images(image_file_ids)
        base_plans: list[tuple[ImageFileEntity, Path, str]] = []
        for image in images:
            source = Path(image.current_path)
            semantic = self._safe_filename(self._preferred_name(image, naming="semantic"), source.suffix)
            base_plans.append((image, source.with_name(semantic), semantic))

        grouped: dict[tuple[Path, str, str], list[tuple[ImageFileEntity, Path, str]]] = {}
        for item in base_plans:
            _image, target, _semantic = item
            grouped.setdefault((target.parent, target.stem, target.suffix), []).append(item)

        available_group_ids = self._available_semantic_group_ids()
        plans: list[RenamePlan] = []
        for key, group in grouped.items():
            selected_ids = {image.id for image, _target, _semantic in group}
            complete_series = selected_ids == available_group_ids.get(key, set())
            for image, source, target in _plan_semantic_series(group, complete_series=complete_series):
                plans.append(
                    RenamePlan(
                        image_file_id=image.id,
                        source_path=source,
                        target_path=target,
                        semantic_name=target.name,
                        would_change=source != target,
                        reason="already_named" if source == target else "semantic_name",
                    )
                )
        return plans

    def rename_file(self, image_file_id: str, *, dry_run: bool = True) -> RenameResult:
        results = self.rename_files([image_file_id], dry_run=dry_run)
        if not results:
            return RenameResult(
                plan=RenamePlan(image_file_id, Path(), Path(), "", False, "missing_image"),
                renamed=False,
                error="image file not found",
            )
        return results[0]

    def rename_files(self, image_file_ids: list[str], *, dry_run: bool = True) -> list[RenameResult]:
        plans = self.plan_rename_many(image_file_ids)
        if dry_run:
            return [RenameResult(plan=plan, renamed=False) for plan in plans]

        results: dict[str, RenameResult] = {}
        actionable: list[RenamePlan] = []
        for plan in plans:
            if not plan.source_path.exists():
                self._mark_missing(plan.image_file_id)
                results[plan.image_file_id] = RenameResult(
                    plan=plan,
                    renamed=False,
                    error="source file not found",
                )
            elif not plan.would_change:
                results[plan.image_file_id] = RenameResult(plan=plan, renamed=False)
            else:
                actionable.append(plan)

        if actionable:
            source_keys = {_path_key(plan.source_path) for plan in actionable}
            conflicts = [
                plan
                for plan in actionable
                if plan.target_path.exists() and _path_key(plan.target_path) not in source_keys
            ]
            if conflicts:
                conflict_names = ", ".join(plan.target_path.name for plan in conflicts)
                error = f"batch rename blocked by existing target(s): {conflict_names}"
                for plan in actionable:
                    results[plan.image_file_id] = RenameResult(plan=plan, renamed=False, error=error)
            else:
                error = self._apply_batch_rename(actionable)
                for plan in actionable:
                    results[plan.image_file_id] = RenameResult(
                        plan=plan,
                        renamed=error is None,
                        error=error,
                    )

        return [results[plan.image_file_id] for plan in plans]

    def export_images(
        self,
        image_file_ids: list[str],
        destination: Path,
        *,
        naming: str = "semantic",
    ) -> ExportImagesResult:
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        copied: list[Path] = []
        skipped = 0
        for image_id in image_file_ids:
            image = self._get_image(image_id)
            if image is None:
                skipped += 1
                continue
            source = Path(image.current_path)
            if not source.exists():
                self._mark_missing(image_id)
                skipped += 1
                continue
            filename = self._safe_filename(self._preferred_name(image, naming=naming), source.suffix)
            target = self._resolve_collision(destination / filename)
            shutil.copy2(source, target)
            copied.append(target)
        return ExportImagesResult(destination=destination, copied=len(copied), skipped=skipped, files=copied)

    def _apply_batch_rename(self, plans: list[RenamePlan]) -> str | None:
        staged: list[tuple[RenamePlan, Path]] = []
        finalized: list[tuple[RenamePlan, Path]] = []
        try:
            for plan in plans:
                temporary = _temporary_rename_path(plan.source_path)
                _rename_path(plan.source_path, temporary)
                staged.append((plan, temporary))
            for plan, temporary in staged:
                _rename_path(temporary, plan.target_path)
                finalized.append((plan, temporary))
            _verify_batch_rename_applied(plans)
            self._update_current_paths(plans)
        except Exception as exc:
            rollback_errors = _rollback_batch_rename(staged, finalized)
            detail = f"; rollback errors: {', '.join(rollback_errors)}" if rollback_errors else ""
            return f"{exc}{detail}"
        return None

    def _get_image(self, image_file_id: str) -> ImageFileEntity | None:
        require_db_ready(self.database_file)
        engine = create_sqlite_engine(self.database_file)
        try:
            with Session(engine) as session:
                return session.get(ImageFileEntity, image_file_id)
        finally:
            engine.dispose()

    def _get_images(self, image_file_ids: list[str]) -> list[ImageFileEntity]:
        if not image_file_ids:
            return []
        require_db_ready(self.database_file)
        engine = create_sqlite_engine(self.database_file)
        try:
            by_id: dict[str, ImageFileEntity] = {}
            with Session(engine) as session:
                for offset in range(0, len(image_file_ids), 900):
                    chunk = image_file_ids[offset:offset + 900]
                    rows = session.exec(
                        select(ImageFileEntity).where(ImageFileEntity.id.in_(chunk))
                    ).all()
                    by_id.update({row.id: row for row in rows})
            return [by_id[image_id] for image_id in image_file_ids if image_id in by_id]
        finally:
            engine.dispose()

    def _available_semantic_group_ids(self) -> dict[tuple[Path, str, str], set[str]]:
        require_db_ready(self.database_file)
        engine = create_sqlite_engine(self.database_file)
        try:
            with Session(engine) as session:
                images = session.exec(
                    select(ImageFileEntity).where(ImageFileEntity.file_status == "available")
                ).all()
        finally:
            engine.dispose()

        grouped: dict[tuple[Path, str, str], set[str]] = {}
        for image in images:
            if not image.current_path:
                continue
            source = Path(image.current_path)
            semantic = self._safe_filename(self._preferred_name(image, naming="semantic"), source.suffix)
            target = source.with_name(semantic)
            grouped.setdefault((target.parent, target.stem, target.suffix), set()).add(image.id)
        return grouped

    def _update_current_paths(self, plans: list[RenamePlan]) -> None:
        engine = create_sqlite_engine(self.database_file)
        try:
            with Session(engine) as session:
                now = datetime.now(timezone.utc)
                for plan in plans:
                    image = session.get(ImageFileEntity, plan.image_file_id)
                    if image is None:
                        raise RuntimeError(f"image file not found during rename: {plan.image_file_id}")
                    image.current_path = str(plan.target_path)
                    image.current_name = plan.target_path.name
                    image.file_status = "available"
                    image.missing_at = None
                    image.updated_at = now
                    session.add(image)
                session.commit()
        finally:
            engine.dispose()

    def _mark_missing(self, image_file_id: str) -> None:
        engine = create_sqlite_engine(self.database_file)
        try:
            with Session(engine) as session:
                image = session.get(ImageFileEntity, image_file_id)
                if image is not None:
                    image.file_status = "missing"
                    image.missing_at = datetime.now(timezone.utc)
                    session.add(image)
                    session.commit()
        finally:
            engine.dispose()

    def _preferred_name(self, image: ImageFileEntity, *, naming: str) -> str:
        if naming == "semantic":
            return image.semantic_name or image.current_name or "image"
        if naming == "current":
            return image.current_name or "image"
        if naming == "hash":
            suffix = Path(image.current_name or "").suffix
            return f"{image.file_hash}{suffix}"
        raise ValueError("naming must be 'semantic', 'current', or 'hash'")

    def _safe_filename(self, name: str, fallback_suffix: str) -> str:
        path = Path(name)
        suffix = path.suffix or fallback_suffix
        stem = path.stem if path.suffix else name
        clean = "".join(c for c in stem if c not in _WIN_FORBIDDEN)
        clean = re.sub(r"[\x00-\x1f]", "", clean)
        clean = re.sub(r"\s+", " ", clean).strip().rstrip(".")
        if not clean:
            clean = "image"
        if clean.upper() in _WIN_RESERVED:
            clean = f"{clean}_"
        return f"{clean[:200]}{suffix}"

    def _resolve_collision(self, target: Path, *, current: Path | None = None) -> Path:
        if current is not None and target == current:
            return target
        if not target.exists():
            return target
        stem, suffix = target.stem, target.suffix
        counter = 2
        while True:
            candidate = target.with_name(f"{stem} - Race {counter:03d}{suffix}")
            if current is not None and candidate == current:
                return candidate
            if not candidate.exists():
                return candidate
            counter += 1


def _indexed_target(target: Path, index: int) -> Path:
    return target.with_name(f"{target.stem} - Race {index:03d}{target.suffix}")


def _plan_semantic_series(
    group: list[tuple[ImageFileEntity, Path, str]],
    *,
    complete_series: bool,
) -> list[tuple[ImageFileEntity, Path, Path]]:
    """Allocate stable or chronological filenames within one semantic-name series."""
    if complete_series:
        return _plan_complete_semantic_series(group)

    ordered = sorted(
        group,
        key=_race_order_key,
    )
    base_target = ordered[0][1]
    occupied = _occupied_series_numbers(base_target)
    planned: list[tuple[ImageFileEntity, Path, Path]] = []
    pending: list[tuple[ImageFileEntity, Path]] = []

    for image, _target, _semantic in ordered:
        source = Path(image.current_path)
        number = _series_number(source, base_target)
        if number is None:
            pending.append((image, source))
        else:
            occupied.add(number)
            planned.append((image, source, source))

    if pending and not occupied:
        if len(pending) == 1:
            image, source = pending.pop(0)
            occupied.add(0)
            planned.append((image, source, base_target))
        else:
            for number, (image, source) in enumerate(pending, start=1):
                occupied.add(number)
                planned.append((image, source, _indexed_target(base_target, number)))
            pending.clear()

    next_number = max((number for number in occupied if number > 0), default=0) + 1
    for image, source in pending:
        while next_number in occupied:
            next_number += 1
        target = _indexed_target(base_target, next_number)
        occupied.add(next_number)
        next_number += 1
        planned.append((image, source, target))

    return planned


def _plan_complete_semantic_series(
    group: list[tuple[ImageFileEntity, Path, str]],
) -> list[tuple[ImageFileEntity, Path, Path]]:
    ordered = sorted(group, key=_race_order_key)
    base_target = ordered[0][1]
    selected_paths = {_path_key(Path(image.current_path)) for image, _target, _semantic in ordered}
    blocked = _occupied_series_numbers(base_target, excluding_paths=selected_paths)

    if len(ordered) == 1 and 0 not in blocked:
        image, _target, _semantic = ordered[0]
        return [(image, Path(image.current_path), base_target)]

    planned: list[tuple[ImageFileEntity, Path, Path]] = []
    next_number = 1
    for image, _target, _semantic in ordered:
        while next_number in blocked:
            next_number += 1
        planned.append((image, Path(image.current_path), _indexed_target(base_target, next_number)))
        next_number += 1
    return planned


def _occupied_series_numbers(
    base_target: Path,
    *,
    excluding_paths: set[str] | None = None,
) -> set[int]:
    excluding_paths = excluding_paths or set()
    try:
        entries = list(base_target.parent.iterdir())
    except OSError:
        return set()
    return {
        number
        for entry in entries
        if (number := _series_number(entry, base_target)) is not None
        and _path_key(entry) not in excluding_paths
    }


def _series_number(path: Path, base_target: Path) -> int | None:
    if path.parent != base_target.parent or path.suffix.casefold() != base_target.suffix.casefold():
        return None
    if path.stem.casefold() == base_target.stem.casefold():
        return 0
    prefix = f"{base_target.stem} - Race "
    if not path.stem.casefold().startswith(prefix.casefold()):
        return None
    number = path.stem[len(prefix):]
    return int(number) if number.isdigit() else None


def _race_order_key(
    item: tuple[ImageFileEntity, Path, str],
) -> tuple[int, float, str, str]:
    image, _target, _semantic = item
    source = Path(image.current_path)
    race_datetime = image.race_datetime
    if race_datetime is not None:
        if race_datetime.tzinfo is None:
            race_datetime = race_datetime.replace(tzinfo=timezone.utc)
        return (0, race_datetime.timestamp(), str(source).casefold(), image.id)
    try:
        return (1, source.stat().st_mtime, str(source).casefold(), image.id)
    except OSError:
        return (2, 0.0, str(source).casefold(), image.id)


def _temporary_rename_path(source: Path) -> Path:
    while True:
        candidate = source.with_name(f".{source.name}.forza-rename-{uuid4().hex}.tmp")
        if not candidate.exists():
            return candidate


def _rename_path(source: Path, target: Path) -> None:
    source.rename(target)
    if not target.exists():
        raise OSError(f"rename target was not created: {target}")
    if _path_key(source) != _path_key(target) and source.exists():
        raise OSError(f"rename source still exists after move: {source}")


def _verify_batch_rename_applied(plans: list[RenamePlan]) -> None:
    missing = [plan.target_path.name for plan in plans if not plan.target_path.exists()]
    if missing:
        raise RuntimeError(
            "batch rename target(s) missing after filesystem rename: "
            + ", ".join(missing)
        )


def _rollback_postcondition_errors(staged: list[tuple[RenamePlan, Path]]) -> list[str]:
    errors: list[str] = []
    for plan, temporary in staged:
        if not plan.source_path.exists():
            errors.append(f"{plan.source_path.name}: rollback did not restore source")
        if temporary.exists():
            errors.append(f"{temporary.name}: rollback temporary remains")
    return errors


def _rollback_batch_rename(
    staged: list[tuple[RenamePlan, Path]],
    finalized: list[tuple[RenamePlan, Path]],
) -> list[str]:
    errors: list[str] = []
    for plan, temporary in reversed(finalized):
        try:
            if plan.target_path.exists():
                _rename_path(plan.target_path, temporary)
        except OSError as exc:
            errors.append(f"{plan.target_path.name}: {exc}")
    for plan, temporary in reversed(staged):
        try:
            if temporary.exists():
                _rename_path(temporary, plan.source_path)
        except OSError as exc:
            errors.append(f"{temporary.name}: {exc}")
    errors.extend(_rollback_postcondition_errors(staged))
    return errors


def _path_key(path: Path) -> str:
    return str(path.resolve(strict=False)).casefold()
