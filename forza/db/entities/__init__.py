from __future__ import annotations

from .base import PromptSnapshotEntity, utc_now
from .run import ExtractionRunEntity, ModelRuntimeSnapshotEntity, RunInputEntity
from .image import ImageFileEntity
from .result import ExtractionAttemptEntity, ExtractionResultEntity, ModelArtifactEntity
from .lap import LapRecordEntity
from .review import ImageFlagEntity, ReviewCaseEntity, ReviewCorrectionEntity
from .export import ExportArtifactEntity
from .reference import ReferenceCarEntity, ReferenceTrackEntity
from .external import ExternalLapRecordEntity, ExternalRecordImportEntity


__all__ = [
    'utc_now',
    'PromptSnapshotEntity',
    'ImageFileEntity',
    'ExtractionRunEntity',
    'RunInputEntity',
    'ModelRuntimeSnapshotEntity',
    'ExtractionResultEntity',
    'ExtractionAttemptEntity',
    'ModelArtifactEntity',
    'LapRecordEntity',
    'ReviewCaseEntity',
    'ReviewCorrectionEntity',
    'ImageFlagEntity',
    'ExportArtifactEntity',
    'ReferenceTrackEntity',
    'ReferenceCarEntity',
    'ExternalRecordImportEntity',
    'ExternalLapRecordEntity',
]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(name)
    from .. import models as _models

    value = getattr(_models, name)
    globals()[name] = value
    return value
