from __future__ import annotations

from tests._gui_write_helpers import *  # noqa: F401,F403

def test_gui_write_service_manages_review_cases_without_manual_flag_surface(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    image_path = tmp_path / "raw.png"
    image_path.write_text("image", encoding="utf-8")
    _image_id, _flag_id, case_id, _ = _seed(db_path, image_path)
    events: list[PipelineEvent] = []

    service = GuiWriteService(db_path, event_sink=events.append)

    assert not hasattr(service, "add_image_flag")
    assert not hasattr(service, "resolve_image_flag")
    assert not hasattr(service, "reopen_image_flag")

    ignored_case = service.ignore_review_case(case_id)
    assert ignored_case is not None
    assert ignored_case.status == "ignored"

    reopened_case = service.reopen_review_case(case_id)
    assert reopened_case is not None
    assert reopened_case.status == "open"

    resolved_case = service.resolve_review_case(case_id)
    assert resolved_case is not None
    assert resolved_case.status == "resolved"

    event_types = [event.type for event in events]
    assert "image_flag_created" not in event_types
    assert "image_flag_changed" not in event_types
    assert "review_case_changed" in event_types


def test_review_case_status_actions_always_touch_updated_at(tmp_path):
    """Regression for B-4b: resolve/ignore/reopen must not skip updated_at."""
    db_path = tmp_path / "forza.sqlite3"
    image_path = tmp_path / "raw.png"
    image_path.write_text("image", encoding="utf-8")
    _image_id, _flag_id, case_id, _ = _seed(db_path, image_path)

    service = GuiWriteService(db_path)

    ignored_case = service.ignore_review_case(case_id)
    assert ignored_case.updated_at is not None

    reopened_case = service.reopen_review_case(case_id)
    assert reopened_case.updated_at is not None
    assert reopened_case.updated_at >= ignored_case.updated_at

    resolved_case = service.resolve_review_case(case_id)
    assert resolved_case.updated_at is not None
    assert resolved_case.updated_at >= reopened_case.updated_at
