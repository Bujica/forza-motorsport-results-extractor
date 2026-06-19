from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, select

from ..db import create_sqlite_engine
from ..db.models import (
    ExportArtifactEntity,
    ExternalLapRecordEntity,
    ExternalRecordImportEntity,
    ExtractionAttemptEntity,
    ExtractionResultEntity,
    ExtractionRunEntity,
    ImageFlagEntity,
    LapRecordEntity,
    ReferenceCarEntity,
    ReferenceTrackEntity,
    ReviewCaseEntity,
    ReviewCorrectionEntity,
    ImageFileEntity,
)

_log = logging.getLogger("forza")


@dataclass(frozen=True)
class DbStatus:
    database_file: Path
    database_exists: bool
    image_files: int
    extraction_runs: int
    extraction_results: int
    lap_records: int
    review_cases: int
    review_corrections: int
    image_flags: int
    export_artifacts: int
    extraction_attempts: int = 0
    reference_tracks: int = 0
    reference_cars: int = 0
    external_record_imports: int = 0
    external_lap_records: int = 0
    schema_state: str = "missing"
    current_revision: str | None = None
    head_revision: str | None = None


class DbSessionProvider:
    """Owns DatabaseService engine lifecycle and DB status reads."""

    def __init__(self, database_file: Path, *, auto_upgrade: bool = False):
        self.database_file = database_file
        self.auto_upgrade = auto_upgrade
        self._engine = None
        self._engine_lock = threading.Lock()

    def close(self) -> None:
        with self._engine_lock:
            if self._engine is not None:
                self._engine.dispose()
                self._engine = None

    def engine_for_db(self):
        if self._engine is None:
            with self._engine_lock:
                if self._engine is None:
                    from ..db.migrate import ensure_db_ready, require_db_ready

                    if self.auto_upgrade:
                        ensure_db_ready(self.database_file)
                    else:
                        require_db_ready(self.database_file)
                    self._engine = create_sqlite_engine(self.database_file)
        return self._engine

    def status(self) -> DbStatus:
        from ..db.migrate import current_revision, detect_database_state, head_revision

        schema_state = detect_database_state(self.database_file).value
        current_rev = current_revision(self.database_file)
        head_rev = head_revision()
        zero = DbStatus(
            database_file=self.database_file,
            database_exists=self.database_file.exists(),
            image_files=0,
            extraction_runs=0,
            extraction_results=0,
            extraction_attempts=0,
            lap_records=0,
            review_cases=0,
            review_corrections=0,
            image_flags=0,
            export_artifacts=0,
            reference_tracks=0,
            reference_cars=0,
            external_record_imports=0,
            external_lap_records=0,
            schema_state=schema_state,
            current_revision=current_rev,
            head_revision=head_rev,
        )
        if not self.database_file.exists():
            return zero
        engine = self._engine if self._engine is not None else create_sqlite_engine(
            self.database_file,
            apply_runtime_pragmas=False,
        )
        owns_engine = self._engine is None
        try:
            with Session(engine) as session:
                return DbStatus(
                    database_file=self.database_file,
                    database_exists=True,
                    image_files=self._count_safe(session, ImageFileEntity),
                    extraction_runs=self._count_safe(session, ExtractionRunEntity),
                    extraction_results=self._count_safe(session, ExtractionResultEntity),
                    extraction_attempts=self._count_safe(session, ExtractionAttemptEntity),
                    lap_records=self._count_safe(session, LapRecordEntity),
                    review_cases=self._count_safe(session, ReviewCaseEntity),
                    review_corrections=self._count_safe(session, ReviewCorrectionEntity),
                    image_flags=self._count_safe(session, ImageFlagEntity),
                    export_artifacts=self._count_safe(session, ExportArtifactEntity),
                    reference_tracks=self._count_safe(session, ReferenceTrackEntity),
                    reference_cars=self._count_safe(session, ReferenceCarEntity),
                    external_record_imports=self._count_safe(session, ExternalRecordImportEntity),
                    external_lap_records=self._count_safe(session, ExternalLapRecordEntity),
                    schema_state=schema_state,
                    current_revision=current_rev,
                    head_revision=head_rev,
                )
        except Exception:
            _log.debug("[db] status() could not query %s", self.database_file, exc_info=True)
            return zero
        finally:
            if owns_engine:
                engine.dispose()

    def status_for_config(self, cfg: Any) -> DbStatus:
        return self.status()

    def _count_safe(self, session: Session, entity_type: type) -> int:
        try:
            return session.exec(select(func.count()).select_from(entity_type)).one()
        except Exception:
            _log.warning("[db] Could not count %s", getattr(entity_type, "__name__", entity_type), exc_info=True)
            return 0


__all__ = ["DbSessionProvider", "DbStatus"]
