from __future__ import annotations

from pathlib import Path


_ENTITY_SOURCE_PATHS = (
    "forza/db/entities/base.py",
    "forza/db/entities/image.py",
    "forza/db/entities/run.py",
    "forza/db/entities/result.py",
    "forza/db/entities/lap.py",
    "forza/db/entities/review.py",
    "forza/db/entities/export.py",
    "forza/db/entities/reference.py",
    "forza/db/entities/external.py",
)


def db_entity_source(root: Path) -> str:
    """Return DB entity source text in the historical models.py class order."""
    return "\n\n".join(
        (root / relative_path).read_text(encoding="utf-8")
        for relative_path in _ENTITY_SOURCE_PATHS
    )
