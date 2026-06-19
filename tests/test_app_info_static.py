from __future__ import annotations

from pathlib import Path

from forza.app_info import (
    APP_BETA_LABEL,
    APP_CHANNEL,
    APP_NAME,
    APP_PACKAGE_NAME,
    APP_RELEASE,
    APP_SHORT_NAME,
    BUILD_INFO_FILENAME,
    ISSUES_URL,
    LEGAL_NOTICE,
    REPOSITORY_URL,
    TARGET_GAME,
    TARGET_SCREEN,
    load_build_info,
)

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_app_info_declares_public_product_identity() -> None:
    assert APP_NAME == "Forza Motorsport Results Extractor"
    assert APP_SHORT_NAME == "FM2023 Results Extractor"
    assert APP_PACKAGE_NAME == "forza-motorsport-results-extractor"
    assert APP_CHANNEL == "beta"
    assert APP_BETA_LABEL == "beta.1"
    assert APP_RELEASE == "0.20.0-beta.1"
    assert BUILD_INFO_FILENAME == "build_info.json"
    assert TARGET_GAME == "Forza Motorsport, 2023 release"
    assert TARGET_SCREEN == "post-race Results screen"
    assert REPOSITORY_URL == "https://github.com/Bujica/forza-motorsport-results-extractor"
    assert ISSUES_URL.endswith("/issues")
    assert "not affiliated" in LEGAL_NOTICE.lower()


def test_version_module_uses_central_app_info() -> None:
    text = _read("forza/version.py")
    assert "from .app_info import APP_BASE_VERSION, APP_NAME, APP_PACKAGE_NAME" in text
    assert "APP_DISPLAY_NAME = APP_NAME" in text
    assert "version(APP_PACKAGE_NAME)" in text
    assert "Forza Motorsport Screenshot Extractor" not in text


def test_gui_exposes_about_repository_and_diagnostics_info() -> None:
    text = _read("forza/gui/main_window.py")
    for token in (
        "_show_about_dialog",
        "_open_repository",
        "_about_diagnostics_text",
        "Copy Diagnostics",
        "Open Repository",
        "QDesktopServices.openUrl",
        "QApplication.clipboard().setText",
    ):
        assert token in text
    assert "APP_SHORT_NAME" in text
    assert "TARGET_GAME" in text
    assert "TARGET_SCREEN" in text
    assert "REPOSITORY_URL" in text


def test_cli_has_version_option_backed_by_display_version() -> None:
    text = _read("forza/cli/parser.py")
    assert "APP_DISPLAY_VERSION" in text
    assert 'root.add_argument("--version", action="version", version=APP_DISPLAY_VERSION)' in text


def test_load_build_info_reads_bundle_metadata(tmp_path) -> None:
    (tmp_path / BUILD_INFO_FILENAME).write_text(
        '{"app_name": "Forza Motorsport Results Extractor", "commit": "abc123"}',
        encoding="utf-8",
    )

    assert load_build_info(tmp_path)["commit"] == "abc123"
    assert load_build_info(tmp_path / "missing") == {}
