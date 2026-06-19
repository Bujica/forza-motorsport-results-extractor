from __future__ import annotations

try:
    from PySide6.QtCore import QObject, Signal
except ImportError:  # pragma: no cover - imported only when GUI extra is installed
    QObject = object  # type: ignore[assignment]

    class Signal:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            raise RuntimeError("PySide6 is required for QtEventBridge")


class QtEventBridge(QObject):
    """Thread-safe event bridge from pipeline workers to Qt widgets.

    The sink may be called from a worker thread. It only emits a Qt signal and
    never touches widgets directly.
    """

    event_received = Signal(object)

    def sink(self, event: object) -> None:
        self.event_received.emit(event)
