from __future__ import annotations

import os

import pytest


def test_confirm_batch_uses_resizable_scrollable_full_preview(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    from forza.gui.widgets.confirmation_dialogs import confirm_batch

    app = widgets.QApplication.instance() or widgets.QApplication([])
    captured: dict[str, object] = {}

    def fake_exec(self):
        preview = self.findChild(widgets.QPlainTextEdit)
        captured["text"] = preview.toPlainText()
        captured["line_wrap"] = preview.lineWrapMode()
        captured["minimum_size"] = (self.minimumWidth(), self.minimumHeight())
        return widgets.QDialog.DialogCode.Accepted

    monkeypatch.setattr(widgets.QDialog, "exec", fake_exec)
    items = [f"file-{index:03d}.png -> renamed-{index:03d}.png" for index in range(40)]

    assert confirm_batch(
        None,
        title="Confirm Metadata Rename",
        action="apply this rename plan",
        names=items,
        summary=["Would rename: 40"],
    )
    assert captured["text"] == "\n".join(items)
    assert captured["line_wrap"] == widgets.QPlainTextEdit.LineWrapMode.NoWrap
    assert captured["minimum_size"] == (640, 420)

    app.processEvents()
