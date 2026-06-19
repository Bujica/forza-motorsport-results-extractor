from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _token(*parts: str) -> str:
    return "".join(parts)


def test_process_view_uses_config_changed_contract_and_refreshes_summary_label() -> None:
    source = _source("forza/gui/views/process_view.py")

    assert "def update_config(self, cfg)" not in source
    assert "def on_config_changed(self, cfg: AppConfig, changes: ConfigChangeSet)" in source
    hook_body = source.split("def on_config_changed(self, cfg: AppConfig, changes: ConfigChangeSet)", 1)[1].split("def _build_ui", 1)[0]
    assert "self._cfg = cfg" in hook_body
    assert "changes.affects(" in hook_body
    assert "self._config_summary.setText(self._run_config_summary())" in hook_body
    assert "self._config_summary = QLabel(self._run_config_summary())" in source
    assert "def _run_config_summary(self)" in source


def test_config_state_is_single_gui_config_writer() -> None:
    state_source = _source("forza/gui/config_state.py")
    assert "class GuiConfigState" in state_source
    assert "ConfigFileService" in state_source
    assert "def save_changes(self, changes" in state_source
    assert "update_config" not in state_source

    for path in (ROOT / "forza" / "gui" / "controllers").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "ConfigFileService(" not in source, path


def test_main_window_uses_central_config_state_and_auto_registration() -> None:
    source = _source("forza/gui/main_window.py")

    assert "self._config_state = GuiConfigState" in source
    assert "connect_many_config_aware(self._config_state, self._controllers)" in source
    assert "def _register_config_aware" in source
    assert "connect_config_aware(self._config_state, component)" in source
    assert "def _apply_saved_config" not in source
    assert "for view in (self._process_view, self._logs_view, self._best_laps_view)" not in source


def test_developer_tool_controllers_use_config_state_at_action_time() -> None:
    rebuild_source = _source("forza/gui/controllers/rebuild_controller.py")
    main_source = _source("forza/gui/main_window.py")

    assert "config_state: GuiConfigState" in rebuild_source
    assert "cfg = self._config_state.current" in rebuild_source
    assert _token("Config", "Bench", "Controller") not in main_source


def test_best_laps_and_logs_views_use_config_changed_contract() -> None:
    logs_source = _source("forza/gui/views/logs_view.py")
    best_laps_source = _source("forza/gui/views/best_laps_view.py")
    main_source = _source("forza/gui/main_window.py")

    assert "def update_config(self, cfg)" not in logs_source
    assert "def update_config(self, cfg)" not in best_laps_source
    assert "def on_config_changed(self, cfg: AppConfig, changes: ConfigChangeSet)" in logs_source
    assert "def on_config_changed(self, cfg: AppConfig, changes: ConfigChangeSet)" in best_laps_source
    assert "self._logs_view._cfg" not in main_source
    assert "self._model = _table_model_for(cfg)" in best_laps_source
    assert "self.table.setModel(self._model)" in best_laps_source


def test_active_developer_tool_views_use_config_changed_contract_for_defaults() -> None:
    logs_source = _source("forza/gui/views/logs_view.py")
    main_source = _source("forza/gui/main_window.py")

    assert "def update_config(self, cfg)" not in logs_source
    assert "def on_config_changed(self, cfg: AppConfig" in logs_source
    assert "ConfigChangeSet" in logs_source
    assert "self._logs_view = self._register_config_aware(LogsView" in main_source
    assert _token("Config", "Bench", "View") not in main_source
    assert _token("Ground", "Truth", "Manager", "View") not in main_source


def test_main_window_lazy_loads_sections_after_process_startup() -> None:
    source = _source("forza/gui/main_window.py")

    assert "self._loaded_sections: set[str] = set()" in source
    assert "self._stack.addWidget(QWidget())" in source
    assert "def _ensure_section_loaded(self, key: str, index: int) -> None:" in source
    assert "self._ensure_section_loaded(item.key, index)" in source
    assert "page = self._page_for(item)" in source

    build_main_body = source.split("def _build_main_area(self) -> QWidget:", 1)[1].split("def _build_command_bar", 1)[0]
    assert "self._page_for(" not in build_main_body

    select_body = source.split("def select_section(self, key: str) -> None:", 1)[1].split("def _handle_runtime_event", 1)[0]
    assert select_body.index("self._ensure_section_loaded(item.key, index)") < select_body.index("self._stack.setCurrentIndex(index)")
