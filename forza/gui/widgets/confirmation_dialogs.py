from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


def confirm_batch(
    parent: QWidget | None,
    *,
    title: str,
    action: str,
    names: Iterable[str],
    summary: Iterable[str] = (),
) -> bool:
    items = list(names)
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setModal(True)
    dialog.resize(960, 680)
    dialog.setMinimumSize(640, 420)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(12)

    prompt = QLabel(f"Confirm action: {action}")
    prompt.setWordWrap(True)
    layout.addWidget(prompt)

    summary_items = list(summary)
    if summary_items:
        summary_label = QLabel("\n".join(summary_items))
        summary_label.setObjectName("mutedLabel")
        summary_label.setWordWrap(True)
        layout.addWidget(summary_label)

    count_label = QLabel(f"Preview items: {len(items)}")
    count_label.setObjectName("mutedLabel")
    layout.addWidget(count_label)

    preview = QPlainTextEdit()
    preview.setReadOnly(True)
    preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    preview.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
    preview.setPlainText("\n".join(items))
    layout.addWidget(preview, 1)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
    )
    buttons.button(QDialogButtonBox.StandardButton.Yes).setObjectName("primaryButton")
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)

    return dialog.exec() == QDialog.DialogCode.Accepted


def info(parent: QWidget | None, *, title: str, message: str) -> None:
    QMessageBox.information(parent, title, message)


def warning(parent: QWidget | None, *, title: str, message: str) -> None:
    QMessageBox.warning(parent, title, message)
