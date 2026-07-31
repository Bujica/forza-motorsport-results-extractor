from __future__ import annotations

from pathlib import Path

from sqlmodel import Session

from ...db.models import ExtractionRunEntity, RunInputEntity
from ...db.repositories import ImageFileRepository
from ..db_session_provider import DbSessionProvider


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
