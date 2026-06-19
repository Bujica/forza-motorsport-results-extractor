from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtCore")

from forza.gui.controllers.image_controller import ImageController
from forza.schemas import ImageFile
from forza.pipeline import file_hash


@dataclass
class _Cfg:
    database_file: Path
    input_dir: Path


class _Reader:
    def __init__(self, images: list[ImageFile]) -> None:
        self.images = images

    def close(self) -> None:
        return None

    def list_images(self, **_filters) -> list[ImageFile]:
        return list(self.images)

    def image_filter_values(self, **_filters):
        return [], []


class _Writer:
    def __init__(self) -> None:
        self.statuses: list[tuple[str, str]] = []

    def close(self) -> None:
        return None

    def set_file_status(self, image_id: str, status: str) -> object:
        self.statuses.append((image_id, status))
        return object()


def test_rescan_images_reconciles_missing_and_available_without_manual_marking(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    existing_path = input_dir / "existing.png"
    existing_path.write_bytes(b"existing")
    changed_path = input_dir / "changed.png"
    changed_path.write_bytes(b"changed-now")
    missing_path = input_dir / "missing.png"

    images = [
        ImageFile(
            id="existing",
            file_hash=file_hash(existing_path),
            current_name=existing_path.name,
            current_path=str(existing_path),
            file_status="missing",
        ),
        ImageFile(
            id="missing",
            file_hash="old-missing-hash",
            current_name=missing_path.name,
            current_path=str(missing_path),
            file_status="available",
        ),
        ImageFile(
            id="changed",
            file_hash="old-changed-hash",
            current_name=changed_path.name,
            current_path=str(changed_path),
            file_status="available",
        ),
    ]
    controller = ImageController(cfg=_Cfg(database_file=tmp_path / "db.sqlite3", input_dir=input_dir))
    writer = _Writer()
    controller._reader = _Reader(images)
    controller._writer = writer
    controller._images = images

    result = controller.rescan_images(["existing", "missing", "changed"])

    assert result.ok is True
    assert writer.statuses == [("existing", "available"), ("missing", "missing")]
    assert "hash changed: 1" in result.message
