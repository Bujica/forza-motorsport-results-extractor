from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget


def _preview_min_size() -> tuple[int, int]:
    """Return (min_width, min_height) for the preview label based on screen geometry."""
    screen = QApplication.primaryScreen()
    if screen is not None:
        geo: QRect = screen.availableGeometry()
        avail_h = geo.height()
        avail_w = geo.width()
        min_h = max(180, int(avail_h * 0.25))
        min_w = max(240, int(avail_w * 0.30))
    else:
        min_h = 360
        min_w = 420
    return (min_w, min_h)


class ImagePreview(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._path: Path | None = None
        self._pixmap: QPixmap | None = None
        self._label = QLabel("Select a case to preview the image.")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setObjectName("imagePreview")
        min_w, min_h = _preview_min_size()
        self._label.setMinimumSize(min_w, min_h)
        self._label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label, 1)

    def set_image_path(self, path: Path | None) -> None:
        self._path = path
        self._pixmap = None
        if path is None:
            self._label.setText("No image linked to this case.")
            self._label.setPixmap(QPixmap())
            return
        if not path.exists():
            self._label.setText(f"Image not found:\n{path}")
            self._label.setPixmap(QPixmap())
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self._label.setText(f"Could not load image:\n{path}")
            self._label.setPixmap(QPixmap())
            return
        self._pixmap = pixmap
        self._update_scaled_pixmap()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._update_scaled_pixmap()

    def _update_scaled_pixmap(self) -> None:
        if self._pixmap is None:
            return
        scaled = self._pixmap.scaled(
            self._label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._label.setPixmap(scaled)
