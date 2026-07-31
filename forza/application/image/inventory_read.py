from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, select

from ...db.models import ImageFileEntity
from ..db_session_provider import DbSessionProvider


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
