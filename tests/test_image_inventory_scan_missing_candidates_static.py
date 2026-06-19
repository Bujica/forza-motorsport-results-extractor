from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMAGE_SERVICE = ROOT / "forza" / "application" / "image_service.py"


def _scan_input_folder_body() -> str:
    source = IMAGE_SERVICE.read_text(encoding="utf-8")
    start = source.index("    def scan_input_folder(")
    end = source.index("\ndef _reconcile_duplicate_hashes", start)
    return source[start:end]


def test_scan_input_folder_filters_missing_candidates_before_path_checks() -> None:
    body = _scan_input_folder_body()

    assert "missing_candidates = session.exec(" in body
    assert "select(ImageFileEntity)" in body
    assert ".where(ImageFileEntity.current_path.is_not(None))" in body
    assert '.where(ImageFileEntity.file_status == "available")' in body
    assert "for image in session.exec(select(ImageFileEntity)).all():" not in body
