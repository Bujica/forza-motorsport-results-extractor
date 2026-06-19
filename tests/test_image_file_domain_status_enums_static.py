from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_image_file_domain_uses_status_enums() -> None:
    domain = (ROOT / "forza" / "schemas" / "domain.py").read_text(encoding="utf-8")
    package_exports = (ROOT / "forza" / "schemas" / "__init__.py").read_text(encoding="utf-8")

    assert "BestLapStatus" in domain
    assert "ImageFileStatus" in domain
    assert "file_status: ImageFileStatus = ImageFileStatus.AVAILABLE" in domain
    assert "best_lap_status: BestLapStatus = BestLapStatus.PENDING" in domain
    assert "current_path: str | None = None" in domain
    assert "current_path: Path | None = None" not in domain
    assert "BestLapStatus" in package_exports
    assert "ImageFileStatus" in package_exports
