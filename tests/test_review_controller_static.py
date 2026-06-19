"""Static tests for ReviewController._advance_to_next() structure and wiring.

Full behavioural tests for the controller require a running Qt application.
These static tests verify the method exists, reloads persisted cases after
write-side decisions, and that the view signals are connected to the controller methods.
"""
from __future__ import annotations

from pathlib import Path


GUI_ROOT = Path(__file__).resolve().parents[1] / "forza" / "gui"
CONTROLLER_SOURCE = (GUI_ROOT / "controllers" / "review_controller.py").read_text(encoding="utf-8")
VIEW_SOURCE = (GUI_ROOT / "views" / "review_queue_view.py").read_text(encoding="utf-8")
MAIN_WINDOW_SOURCE = (GUI_ROOT / "main_window.py").read_text(encoding="utf-8")


# ── _advance_to_next structure ────────────────────────────────────────────────

def test_review_controller_has_advance_to_next_method() -> None:
    assert "def _advance_to_next" in CONTROLLER_SOURCE


def test_review_controller_advance_reloads_cases_from_db_after_decision() -> None:
    """Resolved cases must remain available when the user switches to resolved/all filters."""
    method_body = CONTROLLER_SOURCE.split("def _advance_to_next", 1)[1].split("\n    def ", 1)[0]

    assert 'self._reader.list_review_queue(status="all")' in method_body
    assert "self._apply_current_filters(select_first=False)" in method_body
    assert "self._all_cases = [case for case in self._all_cases if" not in method_body


def test_review_controller_advance_does_not_call_public_refresh() -> None:
    method_body = CONTROLLER_SOURCE.split("def _advance_to_next", 1)[1].split("\n    def ", 1)[0]
    assert "self.refresh(" not in method_body


def test_review_controller_advance_selects_next_open_case() -> None:
    method_body = CONTROLLER_SOURCE.split("def _advance_to_next", 1)[1].split("\n    def ", 1)[0]
    # Must select a subsequent case (index, next, or first remaining)
    has_selection = any(token in method_body for token in (
        "case_selected", "show_selection", "selectRow", "[0]", "next_index",
    ))
    assert has_selection, "_advance_to_next must select the next case automatically"


# ── Semantic decision methods ─────────────────────────────────────────────────

def test_review_controller_has_all_semantic_decision_methods() -> None:
    for method in ("confirm_dirty", "mark_clean", "set_track", "set_weather"):
        assert f"def {method}" in CONTROLLER_SOURCE, f"Missing method: {method}"


def test_review_controller_decision_methods_delegate_to_apply_decision() -> None:
    """confirm_dirty, mark_clean, set_track, set_weather delegate to _apply_decision,
    which centralises the GuiWriteService call and _advance_to_next."""
    for method in ("confirm_dirty", "mark_clean", "set_track", "set_weather"):
        body = CONTROLLER_SOURCE.split(f"def {method}", 1)[1].split("\n    def ", 1)[0]
        assert "_apply_decision" in body, (
            f"{method} must delegate to _apply_decision"
        )


def test_review_controller_apply_decision_calls_advance_to_next() -> None:
    """_apply_decision is the single place that calls _advance_to_next."""
    body = CONTROLLER_SOURCE.split("def _apply_decision", 1)[1].split("\n    def ", 1)[0]
    assert "_advance_to_next" in body, (
        "_apply_decision must call _advance_to_next after a successful decision"
    )


def test_review_controller_apply_decision_calls_gui_write_service() -> None:
    """_apply_decision must call resolve_review_case_with_decision to persist."""
    body = CONTROLLER_SOURCE.split("def _apply_decision", 1)[1].split("\n    def ", 1)[0]
    assert "resolve_review_case_with_decision" in body, (
        "_apply_decision must call GuiWriteService.resolve_review_case_with_decision"
    )


# ── View signal → controller slot wiring ─────────────────────────────────────

def test_review_view_emits_confirm_dirty_signal() -> None:
    assert "confirm_dirty_requested = Signal()" in VIEW_SOURCE
    assert "confirm_dirty_requested" in VIEW_SOURCE


def test_review_view_emits_mark_clean_signal() -> None:
    assert "mark_clean_requested = Signal()" in VIEW_SOURCE


def test_review_view_emits_set_track_signal() -> None:
    assert "set_track_requested = Signal(str)" in VIEW_SOURCE


def test_review_view_emits_set_weather_signal() -> None:
    assert "set_weather_requested = Signal(str)" in VIEW_SOURCE


def test_main_window_connects_review_signals_to_controller() -> None:
    for token in (
        "confirm_dirty_requested.connect",
        "mark_clean_requested.connect",
        "set_track_requested.connect",
        "set_weather_requested.connect",
        "ignore_requested.connect",
    ):
        assert token in MAIN_WINDOW_SOURCE, f"Missing wiring: {token}"


# ── Keyboard shortcuts ────────────────────────────────────────────────────────

def test_review_view_installs_keyboard_shortcuts() -> None:
    assert "_install_shortcuts" in VIEW_SOURCE
    assert "QShortcut" in VIEW_SOURCE


def test_review_view_shortcuts_cover_confirm_and_clean_actions() -> None:
    shortcuts_body = VIEW_SOURCE.split("def _install_shortcuts", 1)[1].split("\n    def ", 1)[0]
    assert "confirm_dirty_requested" in shortcuts_body
    assert "mark_clean_requested" in shortcuts_body
    assert "ignore_requested" in shortcuts_body


# ── Queue empty state ─────────────────────────────────────────────────────────

def test_review_controller_handles_empty_queue_after_last_decision() -> None:
    """After resolving the last case, the controller must handle an empty list."""
    method_body = CONTROLLER_SOURCE.split("def _advance_to_next", 1)[1].split("\n    def ", 1)[0]
    # Must check for empty state (len, not cases, if not, etc.)
    has_empty_check = any(token in method_body for token in (
        "not self._", "len(self._", "if cases", "queue_empty",
        "show_selection(None", "No more",
    ))
    assert has_empty_check, (
        "_advance_to_next must handle the case where the queue is empty "
        "after the last decision"
    )
