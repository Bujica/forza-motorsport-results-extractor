from pathlib import Path

from forza.version import APP_DISPLAY_VERSION, APP_DISPLAY_NAME, __version__


def test_source_version_matches_pyproject() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    expected = next(
        line.split("=", 1)[1].strip().strip('"')
        for line in pyproject.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("version =")
    )

    assert __version__ == expected
    assert APP_DISPLAY_VERSION == f"{APP_DISPLAY_NAME} {expected}"
