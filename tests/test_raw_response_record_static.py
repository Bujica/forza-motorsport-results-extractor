from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_lmstudio_raw_response_json_writer_public_api_is_removed() -> None:
    backend = (ROOT / "forza" / "lmstudio" / "backend.py").read_text(encoding="utf-8")
    package_init = (ROOT / "forza" / "lmstudio" / "__init__.py").read_text(encoding="utf-8")

    assert not (ROOT / "forza" / "lmstudio" / "artifacts.py").exists()
    assert "Raw" + "ResponseRecord" not in package_init
    assert "save_raw" + "_response" not in package_init
    assert "from .artifacts import" not in package_init
    assert "from .artifacts import" not in backend


def test_lmstudio_backend_does_not_write_raw_response_artifacts_by_default() -> None:
    backend = (ROOT / "forza" / "lmstudio" / "backend.py").read_text(encoding="utf-8")

    assert "save_raw" + "_response(" not in backend
    assert "Raw" + "ResponseRecord(" not in backend
    assert "raw_response_artifact_path=str(path)" not in backend
