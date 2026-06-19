from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...config import AppConfig
from ...pipeline import SUPPORTED_IMAGE_EXTENSIONS
from ..config_state import ConfigChangeSet
from ..controllers.process_controller import ProcessSummary
from ..widgets.card import make_card, make_card_title
from ..widgets.event_log import EventLog
from .logs_view import format_runtime_event


_FINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}


class ProcessView(QWidget):
    run_all_requested = Signal()
    select_images_requested = Signal()
    pause_requested = Signal()
    resume_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, *, cfg, parent=None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._paused = False
        self._build_ui()
        self.set_running(False)

    def on_config_changed(self, cfg: AppConfig, changes: ConfigChangeSet) -> None:
        self._cfg = cfg
        if changes.affects("llm", "image", "prompt", "paths.input_dir"):
            self._config_summary.setText(self._run_config_summary())

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        root.addWidget(self._build_run_config_card())
        root.addWidget(self._build_progress_card())
        root.addWidget(self._build_log_card(), 1)

    def _build_run_config_card(self) -> QFrame:
        card = make_card()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(18)
        left = QVBoxLayout()
        left.setSpacing(8)
        left.addWidget(make_card_title("Run Config"))
        checks = QHBoxLayout()
        checks.setSpacing(14)
        self.dry_run = QCheckBox("Dry-run")
        self.force = QCheckBox("Force")
        self.retry_errors = QCheckBox("Retry errors")
        self.debug = QCheckBox("Debug")
        self.force.toggled.connect(self._on_force_toggled)
        self.retry_errors.toggled.connect(self._on_retry_errors_toggled)
        checks.addWidget(self.dry_run)
        checks.addWidget(self.force)
        checks.addWidget(self.retry_errors)
        checks.addWidget(self.debug)
        checks.addStretch(1)
        left.addLayout(checks)

        self._config_summary = QLabel(self._run_config_summary())
        self._config_summary.setObjectName("mutedLabel")
        self._config_summary.setWordWrap(True)
        left.addWidget(self._config_summary)
        layout.addLayout(left, 1)

        self.start_button = QPushButton("Run All")
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self.run_all_requested)
        layout.addWidget(self.start_button)

        self.select_button = QPushButton("Select in Images")
        self.select_button.clicked.connect(self.select_images_requested)
        layout.addWidget(self.select_button)

        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self._toggle_pause)
        layout.addWidget(self.pause_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self._confirm_cancel)
        layout.addWidget(self.cancel_button)
        return card

    def _build_progress_card(self) -> QFrame:
        card = make_card()
        layout = QGridLayout(card)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setHorizontalSpacing(18)
        layout.setVerticalSpacing(10)

        layout.addWidget(make_card_title("Progress"), 0, 0, 1, 4)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress, 1, 0, 1, 4)

        self.status_label = QLabel("Ready")
        self.eta_label = QLabel("ETA: —")
        self.rate_label = QLabel("Rate: — img/min")
        self.count_label = QLabel("0 / 0")
        for label in (self.status_label, self.eta_label, self.rate_label, self.count_label):
            label.setObjectName("mutedLabel")
        layout.addWidget(self.status_label, 2, 0)
        layout.addWidget(self.count_label, 2, 1)
        layout.addWidget(self.rate_label, 2, 2)
        layout.addWidget(self.eta_label, 2, 3)
        return card

    def _build_log_card(self) -> QFrame:
        card = make_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.addWidget(make_card_title("Event Log"))
        header.addStretch(1)
        layout.addLayout(header)

        self.event_log = EventLog()
        layout.addWidget(self.event_log, 1)
        return card

    def _run_config_summary(self) -> str:
        return (
            f"lmstudio · {self._cfg.llm.model} · "
            f"prompt {self._cfg.prompt.active} · {_execution_label(self._cfg.workers)}\n"
            f"{self._cfg.llm.image_format} · {self._cfg.image.max_width}px · "
            f"q{self._cfg.image.encode_quality} · grayscale {'on' if self._cfg.image.grayscale else 'off'} · "
            f"{_pending_screenshots(self._cfg.input_dir)} input image(s)"
        )

    def run_options(self) -> tuple[bool, bool, bool, bool]:
        return (
            self.dry_run.isChecked(),
            self.force.isChecked(),
            self.retry_errors.isChecked(),
            self.debug.isChecked(),
        )

    def _on_force_toggled(self, checked: bool) -> None:
        if checked and self.retry_errors.isChecked():
            self.retry_errors.setChecked(False)

    def _on_retry_errors_toggled(self, checked: bool) -> None:
        if checked and self.force.isChecked():
            self.force.setChecked(False)

    def _toggle_pause(self) -> None:
        if self._paused:
            self.resume_requested.emit()
        else:
            self.pause_requested.emit()

    def _confirm_cancel(self) -> None:
        answer = QMessageBox.question(
            self,
            "Cancel Run",
            "Cancel after the current image? Completed processing will be preserved.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.cancel_requested.emit()

    def set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.dry_run.setEnabled(not running)
        self.force.setEnabled(not running)
        self.retry_errors.setEnabled(not running)
        self.debug.setEnabled(not running)
        self.select_button.setEnabled(not running)
        self.pause_button.setEnabled(running)
        self.cancel_button.setEnabled(running)
        if running:
            self.status_label.setText("Running")
        else:
            self.set_paused(False)
            if self.status_label.text() == "Running":
                self.status_label.setText("Ready")

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self.pause_button.setText("Resume" if paused else "Pause")

    def set_cancelling(self) -> None:
        self.pause_button.setEnabled(False)
        self.cancel_button.setEnabled(False)

    def append_log_line(self, line: str) -> None:
        self.event_log.append_line(line)

    def append_event(self, event) -> None:
        line = format_runtime_event(event)
        if line is not None:
            self.event_log.append_line(line)

    def update_summary(self, summary: ProcessSummary) -> None:
        total = summary.to_process or summary.total
        done = summary.processed
        percent = int(done / total * 100) if total else 0
        self.progress.setValue(max(0, min(100, percent)))
        self.count_label.setText(f"{done} / {total}")
        self.rate_label.setText(f"Rate: {summary.rate_per_min:.1f} img/min" if summary.rate_per_min else "Rate: — img/min")
        self.eta_label.setText(self._eta_text(summary, total, done))
        mode = _run_mode(summary)
        selection = _selection_text(summary)
        if summary.status == "cancelling":
            self.set_cancelling()
        self.status_label.setText(
            f"{summary.status} · {mode}{selection} · duplicates={summary.duplicates} · errors={summary.errors} · review={summary.review_cases}"
        )

    def _eta_text(self, summary: ProcessSummary, total: int, done: int) -> str:
        if summary.status in _FINAL_RUN_STATUSES and summary.elapsed_s > 0:
            return f"Total: {_duration_text(summary.elapsed_s)}"
        if summary.status != "running" or not summary.rate_per_min or not total or done >= total:
            return "ETA: —"
        remaining = max(0, total - done)
        seconds = remaining / summary.rate_per_min * 60.0
        return f"ETA: {_duration_text(seconds)}"


def _execution_label(workers: int) -> str:
    return "Execution: Sequential" if workers <= 1 else f"Execution: Parallel · {workers} workers"


def _duration_text(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _run_mode(summary: ProcessSummary) -> str:
    if summary.retry_errors and summary.dry_run:
        return "retry-errors dry-run"
    if summary.retry_errors:
        return "retry-errors"
    if summary.dry_run:
        return "dry-run"
    return "run"


def _selection_text(summary: ProcessSummary) -> str:
    if not summary.input_total or summary.input_total == summary.total:
        return ""
    return f" · selected {summary.total}/{summary.input_total}"


def _pending_screenshots(input_dir) -> str:
    if not input_dir.exists():
        return "input folder not found"
    count = sum(1 for path in input_dir.iterdir() if path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS)
    return str(count)
