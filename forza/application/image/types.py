from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...pipeline import ImageDiscoveryPlan


@dataclass(frozen=True)
class RenamePlan:
    image_file_id: str
    source_path: Path
    target_path: Path
    semantic_name: str
    would_change: bool
    reason: str = ""


@dataclass(frozen=True)
class RenameResult:
    plan: RenamePlan
    renamed: bool
    error: str | None = None


@dataclass(frozen=True)
class ExportImagesResult:
    destination: Path
    copied: int
    skipped: int
    files: list[Path]


@dataclass(frozen=True)
class ImageInventoryResult:
    plan: ImageDiscoveryPlan
    new_count: int
    existing_count: int
    duplicate_count: int


@dataclass(frozen=True)
class InputFolderScanResult:
    total_files: int
    registered: int
    refreshed: int
    missing: int
    skipped: int
