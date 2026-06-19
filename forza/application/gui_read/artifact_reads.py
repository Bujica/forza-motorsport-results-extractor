from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from sqlmodel import Session, select

from ...db.models import ModelArtifactEntity
from .session_provider import GuiReadSessionProvider


class GuiArtifactReadQueries:
    """Explicit reads for registered artifact files inside caller-approved roots."""

    def __init__(self, session_provider: GuiReadSessionProvider):
        self._session_provider = session_provider

    def read_registered_artifact_text(
        self,
        extraction_result_id: str,
        *,
        artifact_type: str = "raw_response",
        allowed_roots: Sequence[Path],
    ) -> str | None:
        if not self._session_provider.can_read():
            return None
        roots = _normalise_raw_response_roots(allowed_roots)
        if not roots:
            return None
        with self._session_provider.session() as session:
            artifact = _canonical_artifact(session, extraction_result_id, artifact_type=artifact_type)
            return _read_text_file(artifact.file_path if artifact is not None else None, roots)


def _canonical_artifact(session: Session, extraction_result_id: str, *, artifact_type: str) -> ModelArtifactEntity | None:
    return session.exec(
        select(ModelArtifactEntity).where(
            ModelArtifactEntity.extraction_result_id == extraction_result_id,
            ModelArtifactEntity.artifact_type == artifact_type,
            ModelArtifactEntity.is_canonical == True,  # noqa: E712
        )
    ).first()


def _normalise_raw_response_roots(raw_response_roots: Sequence[Path] | None) -> tuple[Path, ...]:
    if raw_response_roots is None:
        return ()
    return tuple(Path(root).resolve() for root in raw_response_roots)


def _read_text_file(path: str | None, allowed_roots: Sequence[Path]) -> str | None:
    if not path or not allowed_roots:
        return None
    try:
        candidate = Path(path).resolve()
    except OSError:
        return None
    if not _is_under_any(candidate, allowed_roots):
        return None
    if not candidate.exists() or not candidate.is_file():
        return None
    try:
        return candidate.read_text(encoding="utf-8")
    except OSError:
        return None


def _is_under_any(candidate: Path, roots: Sequence[Path]) -> bool:
    for root in roots:
        try:
            candidate.relative_to(root)
            return True
        except ValueError:
            continue
    return False
