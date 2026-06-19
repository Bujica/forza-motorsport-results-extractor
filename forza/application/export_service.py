from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from sqlmodel import Session

from ..db.repositories import ExportArtifactRepository, LapRepository
from ..output import export_csv
from ..output import generate_pdf
from ..schemas import ExportLap
from .db_session_provider import DbSessionProvider

if TYPE_CHECKING:
    from .database_service import DatabaseService


class ExportReadService:
    """Owns database-backed export row reads."""

    def __init__(self, session_provider: DbSessionProvider, database_file: Path):
        self._session_provider = session_provider
        self.database_file = Path(database_file)

    def list_full_flat(self, *, run_id: str | None = None) -> list[ExportLap]:
        if not self.database_file.exists():
            return []
        with Session(self._session_provider.engine_for_db()) as session:
            return LapRepository(session).export_flat(run_id=run_id, best_only=False)

    def list_clean_flat(self, *, run_id: str | None = None) -> list[ExportLap]:
        if not self.database_file.exists():
            return []
        with Session(self._session_provider.engine_for_db()) as session:
            return LapRepository(session).export_flat(run_id=run_id, best_only=True)


class ExportArtifactService:
    """Owns export artifact snapshotting and persistence."""

    def __init__(self, session_provider: DbSessionProvider):
        self._session_provider = session_provider

    def record_artifact(self, *, path: Path | str, format: str, run_id: str | None = None) -> None:
        source = Path(path)
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"Export artifact does not exist: {source}")
        data = source.read_bytes()
        artifact_dir = source.parent / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        owner = run_id or "manual"
        snapshot = artifact_dir / f"{source.stem}__{owner}__{hashlib.sha256(data).hexdigest()[:12]}{source.suffix}"
        if snapshot.exists():
            if not snapshot.is_file() or snapshot.read_bytes() != data:
                raise RuntimeError(
                    "Export artifact snapshot is immutable and no longer matches "
                    f"its content-addressed name: {snapshot}"
                )
        else:
            shutil.copy2(source, snapshot)
        with Session(self._session_provider.engine_for_db()) as session:
            ExportArtifactRepository(session).add(path=snapshot, format=format, run_id=run_id)
            session.commit()


class ExportService:
    """Application boundary for user-facing export artifacts."""

    def __init__(self):
        pass

    def clean_csv(self, cfg, out_path: Path, *, run_id: str | None = None) -> int:
        """Export best-lap rows from the relational read model.

        Snapshots are no longer an operational source of truth. If the
        relational database has no best-lap rows, the command returns 0 instead
        of falling back to cached_results/cached_laps.
        """
        with self._database(cfg.database_file) as database:
            database.recompute_best_laps(gamertag=cfg.gamertag)
            results = database.list_clean_flat(run_id=run_id)
        if not results:
            logging.getLogger("forza").warning(
                "[export] no relational best-lap records; run the extractor first"
            )
            return 0
        count = self.csv(results, out_path)
        with self._database(cfg.database_file) as database:
            database.record_artifact(path=out_path, format="csv", run_id=run_id)
        return count

    def csv(self, results: list[ExportLap], out_path: Path) -> int:
        return export_csv(results, out_path)

    def pdf(
        self,
        results: list[ExportLap],
        out_path: Path,
        cfg,
        tracks: list[str],
        *,
        external_records: list[dict] | None = None,
    ) -> None:
        generate_pdf(results, out_path, cfg, tracks, external_records=external_records)

    def _database(self, database_file: Path) -> "DatabaseService":
        from .database_service import DatabaseService

        return DatabaseService(database_file)


__all__ = ["ExportArtifactService", "ExportReadService", "ExportService"]
