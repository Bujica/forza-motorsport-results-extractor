from __future__ import annotations

from pathlib import Path


def test_gui_write_service_lives_in_application_layer() -> None:
    root = Path(__file__).resolve().parents[1]
    assert not (root / "forza" / "gui" / "write_service.py").exists()
    assert (root / "forza" / "application" / "gui_write_service.py").exists()

    gui_init = (root / "forza" / "gui" / "__init__.py").read_text(encoding="utf-8")
    assert "GuiWriteService" not in gui_init
    assert "ReviewDecisionTargetNotFound" not in gui_init

    image_controller = (root / "forza" / "gui" / "controllers" / "image_controller.py").read_text(encoding="utf-8")
    review_controller = (root / "forza" / "gui" / "controllers" / "review_controller.py").read_text(encoding="utf-8")
    assert "application.gui_write_service" in image_controller
    assert "application.gui_write_service" in review_controller
    assert "..write_service" not in image_controller
    assert "..write_service" not in review_controller
