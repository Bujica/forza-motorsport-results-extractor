from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from forza.cli import run as cli_run


class _FakeRunService:
    def __init__(self, status: str, calls: list) -> None:
        self._status = status
        self._calls = calls

    def run(self, cfg, refs, log, *, options):
        self._calls.append((cfg, refs, log, options))
        return self._status


class _FakeDatabase:
    def __init__(self, _database_file, refs, calls) -> None:
        self.refs = refs
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def load_reference_data(self):
        self.calls.append(())
        return self.refs


def _args() -> SimpleNamespace:
    return SimpleNamespace(
        config="config.ini",
        debug=True,
        dry_run=True,
        force=False,
        retry_errors=True,
    )


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(
        log_file=Path("forza.log"),
        database_file=Path("forza.sqlite3"),
    )


def _patch_dependencies(monkeypatch, *, status: str):
    cfg = _cfg()
    refs = object()
    calls = []
    setup_calls = []
    monkeypatch.setattr(cli_run, "load_config", lambda config, strict: cfg)
    monkeypatch.setattr(cli_run, "setup_logging", lambda log_file, *, debug: setup_calls.append((log_file, debug)))
    monkeypatch.setattr(cli_run, "DatabaseService", lambda path: _FakeDatabase(path, refs, []))
    monkeypatch.setattr(cli_run, "RunService", lambda: _FakeRunService(status, calls))
    return cfg, refs, calls, setup_calls


def test_cmd_run_dispatches_completed_run_without_exit(monkeypatch) -> None:
    cfg, refs, calls, setup_calls = _patch_dependencies(monkeypatch, status="completed")

    cli_run.cmd_run(_args())

    assert setup_calls == [(cfg.log_file, True)]
    assert len(calls) == 1
    called_cfg, called_refs, called_log, options = calls[0]
    assert called_cfg is cfg
    assert called_refs is refs
    assert isinstance(called_log, logging.Logger)
    assert called_log.name == "forza"
    assert options.dry_run is True
    assert options.force is False
    assert options.retry_errors is True


def test_cmd_run_cancelled_exits_with_130(monkeypatch) -> None:
    _patch_dependencies(monkeypatch, status="cancelled")

    with pytest.raises(SystemExit) as exc_info:
        cli_run.cmd_run(_args())

    assert exc_info.value.code == 130


def test_cmd_run_failed_status_exits_with_1(monkeypatch) -> None:
    _patch_dependencies(monkeypatch, status="failed")

    with pytest.raises(SystemExit) as exc_info:
        cli_run.cmd_run(_args())

    assert exc_info.value.code == 1


def test_cmd_run_loads_config_strictly_and_sql_reference_data(monkeypatch) -> None:
    cfg = _cfg()
    load_config_calls = []
    load_refs_calls = []
    monkeypatch.setattr(cli_run, "load_config", lambda config, strict: load_config_calls.append((config, strict)) or cfg)
    monkeypatch.setattr(cli_run, "setup_logging", lambda log_file, *, debug: None)
    monkeypatch.setattr(
        cli_run,
        "DatabaseService",
        lambda path: _FakeDatabase(path, object(), load_refs_calls),
    )
    monkeypatch.setattr(cli_run, "RunService", lambda: _FakeRunService("completed", []))

    cli_run.cmd_run(_args())

    assert load_config_calls == [("config.ini", True)]
    assert load_refs_calls == [()]
