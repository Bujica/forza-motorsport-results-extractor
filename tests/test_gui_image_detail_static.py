from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUI_ROOT = ROOT / "forza" / "gui"
SERVICES_ROOT = ROOT / "forza" / "application"

def _gui_read_source() -> str:
    return "\n".join(
        (
            (SERVICES_ROOT / "gui_read_service.py").read_text(encoding="utf-8"),
            (SERVICES_ROOT / "gui_read" / "types.py").read_text(encoding="utf-8"),
            (SERVICES_ROOT / "gui_read" / "image_reads.py").read_text(encoding="utf-8"),
            (SERVICES_ROOT / "gui_read" / "review_reads.py").read_text(encoding="utf-8"),
        )
    )



def test_gui_read_hides_raw_image_flags_and_keeps_source_scoped_review_cases() -> None:
    source = _gui_read_source()

    assert "class GuiImageFlag" not in source
    assert "def list_image_flags(" not in source
    assert "return [_image_flag(row) for row in rows]" not in source
    assert "ReviewCaseEntity.image_file_id == image_file_id" in source


def test_image_detail_controller_uses_read_facade_only() -> None:
    source = (GUI_ROOT / "controllers" / "image_detail_controller.py").read_text(encoding="utf-8")

    assert "GuiReadService" in source
    assert "list_laps(image_file_id=image_file_id)" in source
    assert "list_image_flags(image_file_id=image_file_id, status=\"all\")" not in source
    assert "list_review_queue(status=\"all\", image_file_id=image_file_id)" in source
    assert "list_extraction_results(image_file_id=image_file_id)" in source
    assert "GuiWriteService" not in source


def test_image_detail_view_contains_required_card_sections() -> None:
    source = (GUI_ROOT / "views" / "image_detail_view.py").read_text(encoding="utf-8")

    for token in (
        "ImageDetailDialog",
        "ImagePreview",
        "Metadata",
        "Laps",
        "Review cases",
        "Extractions",
        "Open image debug",
        "← Previous",
        "Next →",
        "set_navigation_state",
        "show_detail",
        "show_error",
    ):
        assert token in source

    assert 'tabs.addTab(self._build_text_tab("flags_text"), "Flags")' not in source
    assert "flags_text" not in source
    assert "_format_flags" not in source


def test_image_detail_review_cases_use_current_canonical_values() -> None:
    source = (GUI_ROOT / "views" / "image_detail_view.py").read_text(encoding="utf-8")

    assert "case.current_track or case.track" in source
    assert "case.current_race_class or case.race_class" in source
    assert "_current_lap_label(case)" in source
    assert "case.best_lap or '—'" not in source


def test_image_detail_dialog_has_decoupled_previous_next_navigation() -> None:
    source = (GUI_ROOT / "views" / "image_detail_view.py").read_text(encoding="utf-8")
    main_window = (GUI_ROOT / "main_window.py").read_text(encoding="utf-8")
    browser = (GUI_ROOT / "views" / "image_browser_view.py").read_text(encoding="utf-8")

    for token in (
        "previous_image_requested = Signal()",
        "next_image_requested = Signal()",
        'self.previous_button = QPushButton("← Previous")',
        'self.next_button = QPushButton("Next →")',
        "def set_navigation_state",
    ):
        assert token in source
    assert "def visible_image_ids" in browser
    assert "self._model.image_at(row)" in browser
    assert "open_detail_requested.connect(self._show_image_detail_from_inventory)" in main_window
    assert "dialog.previous_image_requested.connect(self._show_previous_image_detail)" in main_window
    assert "dialog.next_image_requested.connect(self._show_next_image_detail)" in main_window
    assert "def _show_adjacent_image_detail" in main_window
    navigation_block = main_window.split("def _show_image_detail_from_inventory", 1)[1].split("def _show_image_debug_result", 1)[0]
    assert "self._image_debug_controller" not in navigation_block
    assert "self._diagnostics_view" not in navigation_block


def test_main_window_replaces_image_detail_placeholder_with_dialog() -> None:
    source = (GUI_ROOT / "main_window.py").read_text(encoding="utf-8")

    assert "ImageDetailController" in source
    assert "ImageDetailDialog" in source
    assert "open_image_detail_requested.connect(self._show_image_detail)" in source
    assert "open_detail_requested.connect(self._show_image_detail_from_inventory)" in source
    assert "_show_image_detail_placeholder" not in source


def test_main_window_routes_image_detail_debug_to_real_screen() -> None:
    source = (GUI_ROOT / "main_window.py").read_text(encoding="utf-8")

    assert "ImageDebugController" in source
    assert "ImageDebugView" in source
    assert "self._image_detail_controller.open_debug_requested.connect(self._show_image_debug_result)" in source
    assert "def _show_image_debug_result(self, extraction_result_id: str) -> None:" in source
    assert "self.select_section(\"diagnostics\")" in source
    assert "self._diagnostics_view.select_debug()" in source
    assert "self._image_debug_controller.load_result(extraction_result_id)" in source
    assert "Image Debug will be implemented in stage 7" not in source


def test_status_badge_has_dedicated_theme_rules() -> None:
    widget = (GUI_ROOT / "widgets" / "status_badge.py").read_text(encoding="utf-8")
    theme = (GUI_ROOT / "theme.py").read_text(encoding="utf-8")

    assert "class StatusBadge" in widget
    assert "QLabel#statusBadge" in theme
    assert "kind=\"success\"" in theme
    assert "kind=\"warning\"" in theme
    assert "kind=\"danger\"" in theme

def test_image_detail_extraction_rows_use_prompt_name_not_legacy_prompt_label() -> None:
    source = (GUI_ROOT / "views" / "image_detail_view.py").read_text(encoding="utf-8")
    legacy = "prompt" + "_version"

    assert "result.prompt_name" in source
    assert legacy not in source
