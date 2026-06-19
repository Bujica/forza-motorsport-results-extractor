from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from ...lmstudio import LMStudioRuntimeClient


@dataclass(frozen=True)
class ModelListWorkerResult:
    ok: bool
    models: tuple[str, ...] = ()
    message: str = ""


class ModelListWorker(QObject):
    finished = Signal(object)

    def __init__(self, *, cfg: Any, timeout: float = 1.0) -> None:
        super().__init__()
        self._cfg = cfg
        self._timeout = timeout

    @Slot()
    def run(self) -> None:
        try:
            client = LMStudioRuntimeClient(self._cfg.llm.url, timeout=self._timeout)
            try:
                models = client.list_model_keys()
            finally:
                client.close()
            payload = ModelListWorkerResult(ok=True, models=models)
        except Exception as exc:  # pragma: no cover - GUI boundary
            payload = ModelListWorkerResult(ok=False, message=str(exc))
        self.finished.emit(payload)
