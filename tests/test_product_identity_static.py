from __future__ import annotations

from pathlib import Path

from forza.version import APP_DISPLAY_NAME

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_public_product_identity_names_results_extractor() -> None:
    assert APP_DISPLAY_NAME == "Forza Motorsport Results Extractor"
    assert 'name = "forza-motorsport-results-extractor"' in _read("pyproject.toml")
    assert "Forza Motorsport (2023 release) post-race Results screen" in _read("README.md")
    assert "Target screenshot type: post-race Results screen." in _read("README_BETA.md")


def test_beta_bundle_uses_public_product_names() -> None:
    spec = _read("packaging/forza_motorsport_results_extractor_windows.spec")
    build = _read("tools/build_windows_beta.py")

    assert 'name="Forza Motorsport Results Extractor"' in spec
    assert 'name="fmre-cli"' in spec
    assert 'name="ForzaMotorsportResultsExtractor"' in spec
    assert 'PYINSTALLER_OUTPUT = DIST_DIR / "ForzaMotorsportResultsExtractor"' in build
    assert "ForzaMotorsportResultsExtractor-{_version()}-{BETA_LABEL}-{PLATFORM_LABEL}.zip" in build


def test_public_surface_does_not_keep_old_product_name() -> None:
    public_paths = [
        "README.md",
        "README_BETA.md",
        "pyproject.toml",
        "forza/version.py",
        "forza/cli/parser.py",
        "tools/build_windows_beta.py",
        "packaging/forza_motorsport_results_extractor_windows.spec",
        "docs/release/beta_packaging.md",
        "tests/test_beta_packaging_static.py",
    ]

    for relative_path in public_paths:
        text = _read(relative_path)
        assert "Forza Motorsport Screenshot Extractor" not in text
        assert "forza-screenshot-extractor" not in text
        assert "Forza Extractor.exe" not in text
        assert "forza-cli.exe" not in text
