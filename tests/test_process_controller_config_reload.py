from __future__ import annotations

from pathlib import Path

from forza.config import load_config
from forza.gui.config_state import GuiConfigState
from forza.gui.controllers import process_controller as process_module
from forza.gui.controllers.process_controller import ProcessController
from forza.prompts import DEFAULT_PROMPT_ID


def _write_config(path: Path, *, workers: int) -> None:
    path.write_text(
        "\n".join(
            [
                "[paths]",
                "input_dir = data/input",
                "pdf_file = output/reports/forza_bestlaps.pdf",
                "log_file = output/logs/forza_debug.log",
                "database_file = data/forza.sqlite3",
                "",
                "[user]",
                "gamertag = Bujica89",
                "",
                "[llm]",
                f"workers = {workers}",
                "",
                "[prompt]",
                f"active = {DEFAULT_PROMPT_ID}",
                "",
                "[lmstudio]",
                "url = http://127.0.0.1:1234/v1/chat/completions",
                "model = lmstudio-model",
                "max_completion_tokens = 1000",
                "temperature = 0.0",
                "timeout_connect = 10",
                "timeout_read = 180",
                "max_retries = 3",
                "image_format = png",
                "",
                "[image]",
                "max_width = 2560",
                "encode_quality = 85",
                "grayscale = True",
                "",
                "[validation]",
                "temp_min_f = 40.0",
                "temp_max_f = 140.0",
                "",
                "[pdf]",
                "dirty_lap_symbol = †",
                "show_dirty_lap_symbol = True",
                "",
            ]
        ),
        encoding="utf-8",
    )


class _FakeSignal:
    def __init__(self) -> None:
        self.calls = []

    def emit(self, *args) -> None:
        self.calls.append(args)


class _FakeThread:
    def __init__(self, _parent=None) -> None:
        self.started = _FakeConnectable()
        self.finished = _FakeConnectable()
        self.started_called = False

    def isRunning(self) -> bool:
        return False

    def start(self) -> None:
        self.started_called = True

    def quit(self) -> None:
        pass

    def wait(self, _ms: int) -> bool:
        return True

    def deleteLater(self) -> None:
        pass


class _FakeConnectable:
    def __init__(self) -> None:
        self.connections = []

    def connect(self, callback) -> None:
        self.connections.append(callback)


class _FakeBridge:
    def __init__(self) -> None:
        self.sink = lambda event: None
        self.event_received = _FakeConnectable()


class _FakeWorker:
    instances = []

    def __init__(self, *, cfg, request, event_sink) -> None:
        self.cfg = cfg
        self.request = request
        self.event_sink = event_sink
        self.log_line = _FakeConnectable()
        self.finished = _FakeConnectable()
        _FakeWorker.instances.append(self)

    def run(self) -> None:
        pass

    def moveToThread(self, _thread) -> None:
        pass

    def deleteLater(self) -> None:
        pass

    def request_cancel(self) -> None:
        pass


class _NoInitProcessController(ProcessController):
    def __init__(self, *, config_state: GuiConfigState) -> None:
        # Avoid requiring a QApplication/QObject for this pure controller regression.
        self._config_state = config_state
        self._cfg = config_state.current
        self._debug = False
        self._thread = None
        self._worker = None
        self._bridge = None
        self._started_at = None
        self._run_id = None
        self._total = 0
        self._to_process = 0
        self._processed = 0
        self._errors = 0
        self._duplicates = 0
        self._review_cases = 0
        self._dry_run = False
        self._status = "idle"
        self.run_started = _FakeSignal()
        self.run_finished = _FakeSignal()
        self.pause_state_changed = _FakeSignal()
        self.event_received = _FakeSignal()
        self.log_line_received = _FakeSignal()
        self.summary_changed = _FakeSignal()


def test_process_controller_reloads_config_before_starting_gui_run(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "forza_config.ini"
    _write_config(config_path, workers=1)
    initial_cfg = load_config(config_path, strict=True)
    assert initial_cfg.workers == 1

    config_state = GuiConfigState(cfg=initial_cfg, config_path=str(config_path))
    _write_config(config_path, workers=2)

    monkeypatch.setattr(process_module, "QThread", _FakeThread)
    monkeypatch.setattr(process_module, "QtEventBridge", _FakeBridge)
    monkeypatch.setattr(process_module, "RunWorker", _FakeWorker)
    _FakeWorker.instances = []

    controller = _NoInitProcessController(config_state=config_state)

    assert controller.start_run(dry_run=False, force=False) is True
    assert len(_FakeWorker.instances) == 1
    assert _FakeWorker.instances[0].cfg.workers == 2
    assert _FakeWorker.instances[0].request.retry_errors is False
    assert controller.cfg.workers == 2
    assert config_state.current.workers == 2


def test_process_controller_passes_retry_errors_to_worker(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "forza_config.ini"
    _write_config(config_path, workers=1)
    config_state = GuiConfigState(cfg=load_config(config_path, strict=True), config_path=str(config_path))

    monkeypatch.setattr(process_module, "QThread", _FakeThread)
    monkeypatch.setattr(process_module, "QtEventBridge", _FakeBridge)
    monkeypatch.setattr(process_module, "RunWorker", _FakeWorker)
    _FakeWorker.instances = []

    controller = _NoInitProcessController(config_state=config_state)

    assert controller.start_run(dry_run=False, force=False, retry_errors=True) is True
    assert len(_FakeWorker.instances) == 1
    assert _FakeWorker.instances[0].request.retry_errors is True
