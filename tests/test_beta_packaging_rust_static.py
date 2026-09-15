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
    assert '"RUST_BETA.md"' in text
    assert "Alembic" in text  # documents why no migrations ship
    assert "ForzaMotorsportResultsExtractor-rust-" in text
    assert "fmre-cli" not in text  # Python bundle binary must not leak in
    # No .bat helpers are generated: first launch is self-sufficient.
    assert "BATS" not in text
    assert '"Initialize Database.bat"' not in text
    assert '"DB Doctor.bat"' not in text


def test_rust_beta_manual_covers_first_run() -> None:
    text = _read("RUST_BETA.md")
    for token in (
        "forza-gui.exe",
        "data/input/",
        "database_file",
        "LM Studio",
        "user.gamertag",
        "maintenance db-doctor",
        "config-check",
    ):
        assert token in text


def test_rust_bundle_workflow_is_manual_and_artifact_based() -> None:
    text = _read(".github/workflows/build-windows-beta-rust.yml")
    assert "workflow_dispatch" in text
    assert "dtolnay/rust-toolchain@stable" in text
    assert "pytest tests\\test_beta_packaging_rust_static.py" in text
    assert "python packaging\\build_windows_beta_rust.py" in text
    assert "actions/upload-artifact@v4" in text
    assert "ForzaMotorsportResultsExtractor-rust-*-windows-x64.zip" in text
