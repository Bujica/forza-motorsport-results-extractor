from __future__ import annotations

import logging
from pathlib import Path

from sqlmodel import Session, select

from ...db.models import ExtractionResultEntity, ImageFileEntity
from ...db.repositories import ImageFileRepository, ImageFlagRepository
from ...pipeline import inspect_image_metadata
from ...schemas import ImageMetadata
from ..db_session_provider import DbSessionProvider

_log = logging.getLogger("forza")


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
