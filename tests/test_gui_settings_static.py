from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUI_ROOT = ROOT / "forza" / "gui"


def test_settings_controller_uses_existing_config_validation() -> None:
    source = (GUI_ROOT / "controllers" / "settings_controller.py").read_text(encoding="utf-8")

    assert "validate_config" in source
    assert "ConfigValidationError" in source
    assert "SettingsSnapshot" in source
    assert "paths=self._apply_pending(self._paths())" in source
    assert "llm=self._apply_pending(self._llm())" in source
    assert "runtime=self._apply_pending(self._runtime())" in source
    assert 'SettingsRow("debug", "debug"' not in source
    assert "schema_state" not in source
    assert "_db_status" not in source
    assert '"paths.database_file"' not in source
    assert '"paths.benchmark_file"' not in source
    assert "benchmark_file" not in source


def test_settings_controller_delegates_config_write_to_config_state() -> None:
    source = (GUI_ROOT / "controllers" / "settings_controller.py").read_text(encoding="utf-8")
    state_source = (GUI_ROOT / "config_state.py").read_text(encoding="utf-8")

    assert "GuiConfigState" in source
    assert "self._config_state.validate_changes" in source
    assert "self._config_state.save_changes" in source
    assert "ConfigFileService" not in source
    assert "ConfigFileService" in state_source
    assert "benchmark_file" not in state_source
    assert "write_text" not in source
    assert "configparser" not in source
    assert "GuiWriteService" not in source
    assert "DatabaseService" not in source


def test_settings_view_contains_single_grouped_table_and_validation_banner() -> None:
    source = (GUI_ROOT / "views" / "settings_view.py").read_text(encoding="utf-8")

    for token in (
        "Discard / reload",
        "Save changes",
        "_build_settings_table",
        "_apply_group_spans",
        "setSpan",
        "Paths",
        "Backend / Model / Prompt",
        "Runtime / Image / PDF / Validation",
        "Validation",
        "creates a backup of the current INI",
        "StatusBadge",
        "show_settings",
    ):
        assert token in source
    assert "QTabWidget" not in source
    assert "QScrollArea" not in source
    assert "_settings_section" not in source


def test_settings_view_does_not_import_database_or_config_writers() -> None:
    source = (GUI_ROOT / "views" / "settings_view.py").read_text(encoding="utf-8")

    assert "configparser" not in source
    assert "write_text" not in source


def test_settings_table_model_has_field_value_status_columns() -> None:
    source = (GUI_ROOT / "models" / "settings_table_model.py").read_text(encoding="utf-8")

    assert "Field" in source
    assert "Value" in source
    assert "Status" in source
    assert "set_sections" in source
    assert "_GroupRow" in source
    assert "row.name" in source
    assert "row.value" in source
    assert "row.status" in source


def test_main_window_wires_settings_screen() -> None:
    source = (GUI_ROOT / "main_window.py").read_text(encoding="utf-8")

    assert "SettingsController" in source
    assert "SettingsView" in source
    assert "self._settings_controller = SettingsController" in source
    assert "item.key == \"diagnostics\"" in source
    assert "self._settings_view.refresh_requested.connect(self._settings_controller.refresh)" in source
    assert "self._settings_view.preview_requested.connect(self._settings_controller.preview_changes)" in source
    assert "self._settings_view.save_requested.connect(self._settings_controller.save_changes)" in source
    assert "self._settings_controller.settings_changed.connect(self._settings_view.show_settings)" in source
    assert "self._settings_controller.refresh()" in source
