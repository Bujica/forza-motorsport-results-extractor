"""Backward-compatible facade for `forza.application.image`.

The image services used to live in a single ~1000-line module. They were
split into `forza/application/image/` (one file per class, mirroring the
`gui_read/` package) as part of the 2026-07-31 audit's modular-organization
findings (O-2). This module re-exports the same public names from their new
location so every existing `from .image_service import X` import — including
module-attribute monkeypatching in tests — keeps working unchanged.
"""

from __future__ import annotations

from .image import (
    ExportImagesResult,
    ImageDiscoveryInputService,
    ImageInventoryReadService,
    ImageInventoryResult,
    ImageInventoryService,
    ImageRenameService,
    ImageRetryRegistrationService,
    InputFolderScanResult,
    RenamePlan,
    RenameResult,
)

__all__ = [
    "ExportImagesResult",
    "ImageDiscoveryInputService",
    "ImageInventoryReadService",
    "ImageInventoryResult",
    "ImageInventoryService",
    "ImageRenameService",
    "ImageRetryRegistrationService",
    "InputFolderScanResult",
    "RenamePlan",
    "RenameResult",
]
