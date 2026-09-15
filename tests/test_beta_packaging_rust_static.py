from __future__ import annotations

"""Static guards for the Rust Windows beta bundle (no build, path reads only)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_rust_bundle_script_uses_release_binaries_and_allowlist() -> None:
    text = _read("packaging/build_windows_beta_rust.py")
    assert '"cargo", "build", "--release", "-p", "forza-cli", "-p", "forza-gui"' in text
    assert 'BINARIES = ("forza.exe", "forza-gui.exe")' in text
    assert "FORBIDDEN_BUNDLE_NAMES" in text
    assert "FORBIDDEN_BUNDLE_FILES" in text
    assert "_assert_clean_bundle()" in text
    assert '"Initialize Database.bat"' in text
    assert '"DB Doctor.bat"' in text
    assert '"Config Check.bat"' in text
    assert '"%~dp0forza.exe" maintenance db-upgrade' in text
    assert '"%~dp0forza.exe" maintenance db-doctor --json' in text
    assert '"%~dp0forza.exe" config-check' in text
    assert "Alembic" in text  # documents why no migrations ship
    assert "ForzaMotorsportResultsExtractor-rust-" in text
    assert "RUST_BUNDLE_NOTES.md" in text
    assert "fmre-cli" not in text  # Python bundle binary must not leak in


def test_rust_bundle_workflow_is_manual_and_artifact_based() -> None:
    text = _read(".github/workflows/build-windows-beta-rust.yml")
    assert "workflow_dispatch" in text
    assert "dtolnay/rust-toolchain@stable" in text
    assert "pytest tests\\test_beta_packaging_rust_static.py" in text
    assert "python packaging\\build_windows_beta_rust.py" in text
    assert "actions/upload-artifact@v4" in text
    assert "ForzaMotorsportResultsExtractor-rust-*-windows-x64.zip" in text
