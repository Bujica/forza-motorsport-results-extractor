from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from sqlmodel import Session, select

from ..models import ExportArtifactEntity
from ...schemas import ExportArtifact


class ExportArtifactRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(
        self,
        *,
        path: Path | str,
        format: str,
        run_id: str | None = None,
    ) -> ExportArtifactEntity:
        artifact_path = Path(path)
        data = artifact_path.read_bytes() if artifact_path.exists() and artifact_path.is_file() else None
        try:
            relative_path = str(artifact_path.resolve().relative_to(Path.cwd().resolve()))
        except ValueError:
            relative_path = str(artifact_path)
        entity = ExportArtifactEntity(
            id=uuid4().hex,
            file_path=str(artifact_path),
            relative_path=relative_path,
            artifact_type=format,
            run_id=run_id,
            sha256=hashlib.sha256(data).hexdigest() if data is not None else None,
            size_bytes=len(data) if data is not None else None,
        )
        self.session.add(entity)
        return entity

    def for_run(self, run_id: str) -> list[ExportArtifactEntity]:
        return list(
            self.session.exec(
                select(ExportArtifactEntity).where(ExportArtifactEntity.run_id == run_id)
            )
        )

    def to_schema(self, entity: ExportArtifactEntity) -> ExportArtifact:
        return ExportArtifact(
            path=Path(entity.file_path),
            format=entity.artifact_type,
            run_id=entity.run_id,
        )
