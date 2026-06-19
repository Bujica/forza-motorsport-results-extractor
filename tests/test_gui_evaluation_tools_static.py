from __future__ import annotations

from pathlib import Path


GUI_ROOT = Path(__file__).resolve().parents[1] / "forza" / "gui"


def test_phase_five_polish_is_enforced() -> None:
    main_window = (GUI_ROOT / "main_window.py").read_text(encoding="utf-8")
    theme = (GUI_ROOT / "theme.py").read_text(encoding="utf-8")
    view_sources = "\n".join(path.read_text(encoding="utf-8") for path in (GUI_ROOT / "views").glob("*.py"))

    assert "self._refresh_pending" in main_window
    assert "def _mark_sections_stale" in main_window
    assert "if self._refresh_pending.get(key)" in main_window
    assert "self._section_dirty" not in main_window
    assert "def _mark_sections_dirty" not in main_window
    assert "GUI v0.1 shell" not in main_window
    assert "def _card(" not in view_sources
    assert "placeholderTitle" not in view_sources
    assert "make_card()" in view_sources
    assert "QLabel#cardTitle" in theme
    assert "QLabel(\"Performance\")" not in view_sources
    assert "QLabel(\"Settings\")" not in view_sources
    assert "QLabel(\"Best Laps\")" not in view_sources


def test_diagnostics_contains_central_logs_tab_without_displacing_process_log() -> None:
    main_window = (GUI_ROOT / "main_window.py").read_text(encoding="utf-8")
    diagnostics_view = (GUI_ROOT / "views" / "diagnostics_view.py").read_text(encoding="utf-8")
    logs_view = (GUI_ROOT / "views" / "logs_view.py").read_text(encoding="utf-8")
    process_view = (GUI_ROOT / "views" / "process_view.py").read_text(encoding="utf-8")

    assert "LogsView" in main_window
    assert "def _build_logs_tab" in main_window
    assert "(\"logs\", \"Logs\", self._build_logs_tab)" in main_window
    assert "self.tabs.addTab(container, label)" in diagnostics_view
    assert "removeTab" not in diagnostics_view
    assert "insertTab" not in diagnostics_view
    assert "self._process_controller.log_line_received.connect(self._logs_view.append_log_line)" not in main_window
    assert "self._rebuild_controller.log_line_received.connect(self._logs_view.append_log_line)" not in main_window
    assert "self._logs_view.reload_files()" in main_window
    assert "Technical Logs" in logs_view
    assert "Clear tab" in logs_view
    assert "clear_current_tab" in logs_view
    assert "Application Log" in logs_view
    assert "Errors" in logs_view
    assert "Reload files" not in logs_view
    assert "reload_button" not in logs_view
    assert "Event Log" in process_view
    assert "item.key == \"diagnostics\"" in main_window
    assert "item.key == \"records\"" not in main_window
    assert main_window.index('NavItem("best_laps", "Best Laps"') < main_window.index('NavItem("records", "Records"')
    assert main_window.index('NavItem("records", "Records"') < main_window.index('NavItem("diagnostics", "Diagnostics"')
    assert "DiagnosticsView" in main_window
    assert "Diagnostics" in main_window
    legacy_section_key = "developer" + "_tools"
    assert legacy_section_key not in main_window
    legacy_view_file = "developer" + "_tools_view.py"
    assert not (GUI_ROOT / "views" / legacy_view_file).exists()
    assert (GUI_ROOT / "views" / "diagnostics_view.py").exists()


def test_diagnostics_exposes_current_runtime_tabs() -> None:
    main_window = (GUI_ROOT / "main_window.py").read_text(encoding="utf-8")

    for tab in (
        "Overview",
        "Image Debug",
        "DB Doctor",
        "Logs",
    ):
        assert tab in main_window


def test_db_doctor_tab_refreshes_when_diagnostics_are_stale() -> None:
    main_window = (GUI_ROOT / "main_window.py").read_text(encoding="utf-8")

    assert 'elif key == "db_doctor" and self._db_doctor_view is not None:' in main_window
    assert "self._db_doctor_controller.refresh()" in main_window
    assert 'self._refresh_pending["diagnostics"] = False' in main_window


def test_developer_overview_exposes_lmstudio_runtime_details_without_api_calls_in_view() -> None:
    view = (GUI_ROOT / "views" / "developer_overview_view.py").read_text(encoding="utf-8")
    worker = (GUI_ROOT / "workers" / "developer_overview_worker.py").read_text(encoding="utf-8")
    redundant_title = "Diagnostics " + "Overview"
    assert redundant_title not in view
    assert "root.addLayout(self._build_toolbar())" in view
    assert "def _build_toolbar(self) -> QHBoxLayout:" in view
    assert 'self.refresh_button = QPushButton("Refresh")' in view

    for expected in (
        "lm_endpoint_text",
        "lm_model_text",
        "lm_instance_text",
        "lm_configured_load_text",
        "lm_configured_request_text",
        "lm_configured_image_text",
        "lm_runtime_policy_text",
        "lm_loaded_runtime_text",
        "lm_capabilities_text",
        "lm_info_text",
        "lm_warnings_text",
    ):
        assert expected in view
    assert "LMStudioRuntimeClient" not in view
    assert "runtime_status(" in worker
    assert "desired_load_config" in worker
