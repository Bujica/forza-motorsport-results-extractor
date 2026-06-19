from __future__ import annotations

import importlib
from pathlib import Path

from forza.application.image_service import ImageRenameService, RenamePlan

MODULE = importlib.import_module("forza.application.image_service")


def _plan(image_id: str, source: Path, target: Path) -> RenamePlan:
    return RenamePlan(
        image_file_id=image_id,
        source_path=source,
        target_path=target,
        semantic_name=target.name,
        would_change=True,
        reason="semantic_name",
    )


def test_image_rename_service_rolls_back_filesystem_when_db_update_fails(tmp_path, monkeypatch):
    source_a = tmp_path / "Screenshot A.png"
    source_b = tmp_path / "Screenshot B.png"
    target_a = tmp_path / "Track - A - Race 001.png"
    target_b = tmp_path / "Track - A - Race 002.png"
    source_a.write_text("a", encoding="utf-8")
    source_b.write_text("b", encoding="utf-8")

    service = ImageRenameService(tmp_path / "missing.sqlite3")

    def fail_update(_plans):
        raise RuntimeError("db update failed")

    monkeypatch.setattr(service, "_update_current_paths", fail_update)

    error = service._apply_batch_rename(
        [
            _plan("img-a", source_a, target_a),
            _plan("img-b", source_b, target_b),
        ]
    )

    assert error is not None
    assert "db update failed" in error
    assert source_a.read_text(encoding="utf-8") == "a"
    assert source_b.read_text(encoding="utf-8") == "b"
    assert not target_a.exists()
    assert not target_b.exists()
    assert not any("forza-rename" in path.name for path in tmp_path.iterdir())


def test_rollback_reports_unrestored_source_when_temporary_disappears(tmp_path):
    source = tmp_path / "Screenshot.png"
    target = tmp_path / "Track - A.png"
    temporary = tmp_path / ".Screenshot.png.forza-rename-test.tmp"

    errors = MODULE._rollback_batch_rename(
        [(_plan("img", source, target), temporary)],
        [],
    )

    assert any("rollback did not restore source" in error for error in errors)


def test_batch_rename_verifies_targets_before_database_update(tmp_path):
    source = tmp_path / "Screenshot.png"
    target = tmp_path / "Track - A.png"

    try:
        MODULE._verify_batch_rename_applied([_plan("img", source, target)])
    except RuntimeError as exc:
        assert "batch rename target(s) missing" in str(exc)
    else:
        raise AssertionError("missing rename target was not reported")
