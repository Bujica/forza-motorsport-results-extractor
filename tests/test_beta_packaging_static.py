from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_beta_launcher_defaults_to_gui_and_keeps_cli_escape_hatch() -> None:
    text = _read("forza/beta_launcher.py")
    assert "run_gui(config_path=\"forza_config.ini\", debug=False)" in text
    assert "from forza.cli.main import main as cli_main" in text
    assert "len(sys.argv) > 1" in text
    assert "os.chdir(_portable_root())" in text


def test_pyinstaller_spec_uses_allowlisted_runtime_data() -> None:
    text = _read("packaging/forza_motorsport_results_extractor_windows.spec")
    assert "forza/beta_launcher.py" in text.replace('" / "', '/')
    assert "ROOT = Path(SPECPATH).resolve().parent" in text
    assert "parent.parent" not in text
    assert "forza/db/migrations" in text
    assert "logging.config" in text
    assert 'excludes=["tests", "tools"]' in text
    assert 'name="Forza Motorsport Results Extractor"' in text
    assert 'name="fmre-cli"' in text
    assert "console=False" in text
    assert "console=True" in text


def test_beta_build_script_excludes_developer_and_private_runtime_files() -> None:
    text = _read("tools/build_windows_beta.py")
    for token in ("tools", "scripts", "tests", ".git", ".github"):
        assert f'"{token}"' in text
    for token in ("data/forza.sqlite3", "data/external/DataFM.xlsx"):
        assert f'"{token}"' in text
    for token in ("README_BETA.md", "cars.txt", "tracks.txt", "data/external/track_aliases.json"):
        assert f'"{token}"' in text
    assert "PyInstaller" in text
    assert "spec_from_file_location" in text
    assert "import install" not in text
    assert "ForzaMotorsportResultsExtractor-{_version()}-{BETA_LABEL}-{PLATFORM_LABEL}.zip" in text
    assert "BUILD_INFO_FILENAME" in text
    assert "def _write_build_info()" in text
    assert '["git", "rev-parse", "--short=12", "HEAD"]' in text
    assert "def _remove_forbidden_bundle_artifacts()" in text
    assert "_remove_forbidden_bundle_artifacts()" in text
    assert "shutil.rmtree(cache_dir)" in text


def test_beta_readme_documents_inclusions_and_exclusions() -> None:
    text = _read("README_BETA.md")
    for token in (
        "LM Studio",
        "Model weights",
        "data/forza.sqlite3",
        "tools/",
        "scripts/",
        "tests/",
        ".github/",
        "DataFM.xlsx",
        "Initialize Database.bat",
    ):
        assert token in text


def test_pyproject_declares_build_extra() -> None:
    text = _read("pyproject.toml")
    assert "build = [" in text
    assert "pyinstaller>=6.0" in text


def test_windows_beta_workflow_is_manual_and_artifact_based() -> None:
    text = _read(".github/workflows/build-windows-beta.yml")
    assert "workflow_dispatch" in text
    assert "python -m pip install -e .[dev,gui,build]" in text
    assert "python tools\\build_windows_beta.py" in text
    assert "actions/upload-artifact@v4" in text


def test_packaging_documentation_states_one_folder_policy() -> None:
    text = _read("docs/release/beta_packaging.md")
    assert "one-folder" in text
    assert "tools/" in text
    assert "scripts/" in text
    assert "DataFM.xlsx" in text
    assert "ForzaMotorsportResultsExtractor-0.20.0-beta.1-windows-x64.zip" in text
