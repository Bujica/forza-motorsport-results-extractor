from __future__ import annotations

from types import SimpleNamespace
import importlib

import pytest

artifact_checks = importlib.import_module("forza.application.db_doctor.artifact_checks")
image_file_checks = importlib.import_module("forza.application.db_doctor.image_file_checks")


class _ExecRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def exec(self, _query):
        return _ExecRows(self._rows)

    def get(self, *_args, **_kwargs):
        return None


def test_available_image_check_uses_hash_suffix_size_before_hash(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"current bytes")
    expected_hash = "0" * 64 + "_999"

    def fail_file_hash(_path):
        raise AssertionError("file_hash should not run when persisted size already differs")

    monkeypatch.setattr(image_file_checks, "file_hash", fail_file_hash)

    missing, mismatched = image_file_checks._available_image_file_checks(
        _FakeSession([(str(image_path), expected_hash)])
    )

    assert (missing, mismatched) == (0, 1)


def test_available_image_check_still_hashes_when_size_matches(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"same size")
    expected_hash = "expected_hash_9"
    calls = []

    def fake_file_hash(path):
        calls.append(path)
        return expected_hash

    monkeypatch.setattr(image_file_checks, "file_hash", fake_file_hash)

    missing, mismatched = image_file_checks._available_image_file_checks(
        _FakeSession([(str(image_path), expected_hash)])
    )

    assert (missing, mismatched) == (0, 0)
    assert calls == [image_path]


def test_model_artifact_size_mismatch_skips_sha256_file(tmp_path, monkeypatch) -> None:
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text("actual content", encoding="utf-8")
    artifact = SimpleNamespace(
        file_path=str(artifact_path),
        size_bytes=999,
        sha256="0" * 64,
        artifact_type="request_preview",
        attempt_id=None,
    )

    def fail_sha256_file(_path):
        raise AssertionError("_sha256_file should not run when persisted size already differs")

    monkeypatch.setattr(artifact_checks, "_sha256_file", fail_sha256_file)

    assert artifact_checks._invalid_file_artifacts(_FakeSession(), [artifact]) == 1


def test_model_artifact_still_hashes_when_size_matches(tmp_path, monkeypatch) -> None:
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text("actual", encoding="utf-8")
    artifact = SimpleNamespace(
        file_path=str(artifact_path),
        size_bytes=6,
        sha256="expected",
        artifact_type="request_preview",
        attempt_id=None,
    )
    calls = []

    def fake_sha256_file(path):
        calls.append(path)
        return "expected"

    monkeypatch.setattr(artifact_checks, "_sha256_file", fake_sha256_file)

    assert artifact_checks._invalid_file_artifacts(_FakeSession(), [artifact]) == 0
    assert calls == [artifact_path]
