from __future__ import annotations

from threading import Event
from threading import Lock
import time


class RunCancelled(Exception):
    """Raised at cooperative checkpoints when a run was cancelled."""


class RunControl:
    """Thread-safe cooperative pause/cancel state for long extraction runs."""

    def __init__(self) -> None:
        self._resume_gate = Event()
        self._resume_gate.set()
        self._cancelled = Event()
        self._timing_lock = Lock()
        self._paused_started: float | None = None
        self._paused_total = 0.0

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def paused(self) -> bool:
        return not self._resume_gate.is_set() and not self.cancelled

    def pause(self) -> None:
        if not self.cancelled:
            with self._timing_lock:
                if self._paused_started is None:
                    self._paused_started = time.monotonic()
            self._resume_gate.clear()

    def resume(self) -> None:
        self._finish_pause()
        self._resume_gate.set()

    def cancel(self) -> None:
        self._cancelled.set()
        self._finish_pause()
        self._resume_gate.set()

    def checkpoint(self) -> None:
        self._resume_gate.wait()
        if self.cancelled:
            raise RunCancelled()

    @property
    def paused_duration_s(self) -> float:
        with self._timing_lock:
            current = (
                time.monotonic() - self._paused_started
                if self._paused_started is not None
                else 0.0
            )
            return self._paused_total + current

    def elapsed_since(self, started_at: float) -> float:
        return max(0.0, time.monotonic() - started_at - self.paused_duration_s)

    def _finish_pause(self) -> None:
        with self._timing_lock:
            if self._paused_started is not None:
                self._paused_total += time.monotonic() - self._paused_started
                self._paused_started = None
