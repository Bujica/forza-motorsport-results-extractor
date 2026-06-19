from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUI_ROOT = ROOT / "forza" / "gui"


def test_images_sync_uses_worker_boundary() -> None:
    controller = (GUI_ROOT / "controllers" / "image_controller.py").read_text(encoding="utf-8")
    worker = (GUI_ROOT / "workers" / "image_inventory_worker.py").read_text(encoding="utf-8")
    main_window = (GUI_ROOT / "main_window.py").read_text(encoding="utf-8")
    view = (GUI_ROOT / "views" / "image_browser_view.py").read_text(encoding="utf-8")

    assert "ImageInventoryWorker" in controller
    assert "QThread" in controller
    assert "scan_running_changed = Signal(bool)" in controller
    assert "def _scan_input_folder" not in controller
    assert "DatabaseService" not in controller
    assert "ImageInventoryService" not in controller

    assert "finished = Signal(object)" in worker
    assert "ImageInventoryService(database).scan_input_folder" in worker

    assert "self._image_controller.scan_running_changed.connect(self._image_view.set_syncing)" in main_window
    assert "def set_syncing(self, running: bool)" in view
    assert "Syncing input folder..." in view


def test_images_sync_worker_signal_is_documented() -> None:
    docs = (ROOT / "docs" / "contracts" / "gui_signal_payloads.md").read_text(encoding="utf-8")

    assert "`forza/gui/workers/image_inventory_worker.py::finished`" in docs
