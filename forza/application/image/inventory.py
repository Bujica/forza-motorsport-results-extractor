from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session, select

from ...db import create_sqlite_engine
from ...db.migrate import require_db_ready
from ...db.models import ExtractionResultEntity, ImageFileEntity, ImageFlagEntity
from ...db.repositories import ImageFileRepository, ImageFlagRepository
from ...pipeline import file_hash, find_images, inspect_image_metadata, log_duplicate_skips, plan_images
from .types import ImageInventoryResult, InputFolderScanResult

_log = logging.getLogger("forza")


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
