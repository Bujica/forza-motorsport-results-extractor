from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlmodel import Session, select

from ..models import ImageFileEntity
from ...schemas import ImageMetadata, ImageFile


def _path_str(value: Path | str | None) -> str | None:
    return str(value) if value is not None else None


class ImageFileRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert(
        self,
        *,
        file_hash: str,
        file_name: str | None = None,
        current_path: Path | str | None = None,
        path: Path | str | None = None,
        current_name: str | None = None,
        semantic_name: str | None = None,
        image_id: str | None = None,
        duplicate_of_image_file_id: str | None = None,
        best_lap_status: str | None = None,
        metadata: ImageMetadata | None = None,
    ) -> ImageFileEntity:
        if path is not None:
            current_path = current_path or path
        resolved_current_path = _path_str(current_path) or file_name
        resolved_current_name = (
            current_name
            or (Path(resolved_current_path).name if resolved_current_path else None)
            or file_name
            or "image"
        )
        now = datetime.now(timezone.utc)
        existing = self._existing_physical_file(
            file_hash=file_hash,
            image_id=image_id,
            current_path=resolved_current_path,
        )
        if resolved_current_path:
            previous_owners = self.session.exec(
                select(ImageFileEntity).where(
                    ImageFileEntity.current_path == resolved_current_path,
                    ImageFileEntity.file_hash != file_hash,
                    ImageFileEntity.file_status == "available",
                )
            ).all()
            for previous in previous_owners:
                previous.file_status = "missing"
                previous.missing_at = now
                previous.updated_at = now
                self.session.add(previous)
        if existing is not None:
            if current_path is not None:
                existing.current_path = _path_str(current_path) or existing.current_path
                existing.current_name = resolved_current_name
            elif current_name is not None:
                existing.current_name = current_name
            if semantic_name is not None:
                existing.semantic_name = semantic_name
            if best_lap_status is not None:
                existing.best_lap_status = best_lap_status
            if metadata is not None:
                _apply_metadata(existing, metadata)
            if duplicate_of_image_file_id is not None:
                existing.duplicate_of_image_file_id = duplicate_of_image_file_id
            if existing.current_path and not Path(existing.current_path).exists():
                existing.file_status = "missing"
                existing.missing_at = datetime.now(timezone.utc)
            else:
                existing.file_status = "available"
                existing.missing_at = None
            existing.updated_at = now
            self.session.add(existing)
            return existing

        entity = ImageFileEntity(
            id=image_id or uuid4().hex,
            file_hash=file_hash,
            duplicate_of_image_file_id=duplicate_of_image_file_id,
            current_name=resolved_current_name,
            semantic_name=semantic_name,
            current_path=resolved_current_path or resolved_current_name,
            best_lap_status=best_lap_status or "pending",
        )
        if metadata is not None:
            _apply_metadata(entity, metadata)
        self.session.add(entity)
        return entity

    def _existing_physical_file(
        self,
        *,
        file_hash: str,
        image_id: str | None,
        current_path: str | None,
    ) -> ImageFileEntity | None:
        if image_id is not None:
            entity = self.by_id(image_id)
            if entity is not None and entity.file_hash == file_hash:
                return entity
        if current_path is None:
            return None
        entity = self.by_current_path(current_path)
        if entity is None:
            return None
        if entity.file_hash == file_hash:
            return entity
        return None

    def by_hash(self, file_hash: str) -> ImageFileEntity | None:
        return self.session.exec(
            select(ImageFileEntity)
            .where(ImageFileEntity.file_hash == file_hash)
            .order_by(ImageFileEntity.created_at.asc())
        ).first()

    def by_current_path(self, current_path: str | Path | None) -> ImageFileEntity | None:
        if current_path is None:
            return None
        return self.session.exec(
            select(ImageFileEntity).where(ImageFileEntity.current_path == str(current_path))
        ).first()

    def by_id(self, image_id: str) -> ImageFileEntity | None:
        return self.session.get(ImageFileEntity, image_id)

    def set_best_lap_status(self, image_id: str, status: str) -> ImageFileEntity | None:
        entity = self.by_id(image_id)
        if entity is None:
            return None
        entity.best_lap_status = status
        entity.updated_at = datetime.now(timezone.utc)
        self.session.add(entity)
        return entity

    def to_schema(self, entity: ImageFileEntity) -> ImageFile:
        """Convert a DB entity to the domain schema.

        Note: the legacy ``path`` field has been removed from ``ImageFile``.
        Callers should use ``current_path`` as the authoritative physical path.
        """
        return ImageFile(
            id=entity.id,
            file_hash=entity.file_hash,
            duplicate_of_image_file_id=entity.duplicate_of_image_file_id,
            semantic_name=entity.semantic_name,
            current_name=entity.current_name,
            current_path=entity.current_path,
            file_status=entity.file_status,
            best_lap_status=entity.best_lap_status,
            file_size_bytes=entity.size_bytes,
            image_format=entity.image_format,
            mime_type=entity.mime_type,
            width_px=entity.width_px,
            height_px=entity.height_px,
            bit_depth=entity.bit_depth,
            color_mode=entity.color_mode,
            file_modified_at=entity.file_modified_at,
            race_datetime=entity.race_datetime,
            race_date=entity.race_date,
            race_datetime_source=entity.race_datetime_source,
            image_metadata_json=entity.image_metadata_json or {},
        )


def _apply_metadata(entity: ImageFileEntity, metadata: ImageMetadata) -> None:
    entity.size_bytes = metadata.file_size_bytes
    entity.image_format = metadata.image_format
    entity.mime_type = metadata.mime_type
    entity.width_px = metadata.width_px
    entity.height_px = metadata.height_px
    entity.bit_depth = metadata.bit_depth
    entity.color_mode = metadata.color_mode
    entity.file_modified_at = metadata.file_modified_at
    entity.race_datetime = metadata.race_datetime
    entity.race_date = metadata.race_date
    entity.race_datetime_source = metadata.race_datetime_source
    metadata_json = dict(metadata.image_metadata_json or {})
    metadata_json.pop("duplicate_of_image_file_id", None)
    metadata_json.pop("file_modified_at", None)
    entity.image_metadata_json = metadata_json

