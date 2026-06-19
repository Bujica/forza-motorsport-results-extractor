from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUI_ROOT = ROOT / "forza" / "gui"
SERVICES_ROOT = ROOT / "forza" / "gui"


def test_config_file_service_validates_backs_up_and_writes_ini() -> None:
    source = (ROOT / "forza" / "application" / "config_service.py").read_text(encoding="utf-8")

    assert "class ConfigFileService" in source
    assert "def save_changes" in source
    assert "validate_config(candidate)" in source
    assert "shutil.copy2" in source
    assert "configparser.ConfigParser" in source
    assert "parser.write(handle)" in source
    assert "ConfigSaveResult" in source


def test_config_file_service_limits_writable_fields() -> None:
    source = (ROOT / "forza" / "application" / "config_service.py").read_text(encoding="utf-8")

    for token in (
        "paths.",
        "llm.",
        "image.",
        "validation.",
        "pdf.",
        "prompt.active",
        "user.gamertag",
        "Field is not editable",
    ):
        assert token in source


def test_settings_controller_delegates_file_write_to_gui_config_state() -> None:
    source = (GUI_ROOT / "controllers" / "settings_controller.py").read_text(encoding="utf-8")
    state_source = (GUI_ROOT / "config_state.py").read_text(encoding="utf-8")

    assert "GuiConfigState" in source
    assert "self._config_state.save_changes" in source
    assert "self._config_state.validate_changes" in source
    assert "preview_changes" in source
    assert "action_completed" in source
    assert "action_failed" in source
    assert "ConfigFileService" not in source
    assert "ConfigFileService" in state_source
    assert "write_text" not in source
    assert "parser.write" not in source


def test_settings_model_is_editable_only_for_value_column() -> None:
    source = (GUI_ROOT / "models" / "settings_table_model.py").read_text(encoding="utf-8")

    assert "value_changed = Signal(str, str)" in source
    assert "def setData" in source
    assert "index.column() != 1" in source
    assert "ItemIsEditable" in source
    assert "getattr(row, \"editable\", False)" in source


def test_settings_view_has_save_discard_and_confirmation_flow() -> None:
    source = (GUI_ROOT / "views" / "settings_view.py").read_text(encoding="utf-8")

    for token in (
        "Save changes",
        "Discard / reload",
        "preview_requested",
        "save_requested",
        "confirm_batch",
        "validate, back up, and save INI changes",
        "show_message",
        "show_warning",
    ):
        assert token in source


def test_main_window_and_app_pass_config_path_to_settings() -> None:
    main_window = (GUI_ROOT / "main_window.py").read_text(encoding="utf-8")
    app = (GUI_ROOT / "app.py").read_text(encoding="utf-8")

    assert "config_path: str" in main_window
    assert "self._config_path = config_path" in main_window
    assert "self._config_state = GuiConfigState" in main_window
    assert "SettingsController(" in main_window
    assert "config_state=self._config_state" in main_window
    assert "preview_requested.connect(self._settings_controller.preview_changes)" in main_window
    assert "save_requested.connect(self._settings_controller.save_changes)" in main_window
    assert "config_path=str(config_path)" in app
