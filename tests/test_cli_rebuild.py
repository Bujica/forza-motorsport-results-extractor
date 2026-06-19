from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

from forza.cli import rebuild as cli_rebuild


class _FakeRebuildService:
    def __init__(self, calls: list) -> None:
        self._calls = calls

    def rebuild_outputs(self, cfg, refs, log):
        self._calls.append((cfg, refs, log))


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


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(
        log_file=Path("forza.log"),
        database_file=Path("forza.sqlite3"),
    )


def _args(*, debug: bool = False) -> SimpleNamespace:
    return SimpleNamespace(config="config.ini", debug=debug)


def _patch_dependencies(monkeypatch):
    cfg = _cfg()
    refs = object()
    rebuild_calls = []
    setup_calls = []
    load_config_calls = []
    load_refs_calls = []
    monkeypatch.setattr(cli_rebuild, "load_config", lambda config: load_config_calls.append(config) or cfg)
    monkeypatch.setattr(cli_rebuild, "setup_logging", lambda log_file, *, debug: setup_calls.append((log_file, debug)))
    monkeypatch.setattr(
        cli_rebuild,
        "DatabaseService",
        lambda path: _FakeDatabase(path, refs, load_refs_calls),
    )
    monkeypatch.setattr(cli_rebuild, "RebuildService", lambda: _FakeRebuildService(rebuild_calls))
    return cfg, refs, rebuild_calls, setup_calls, load_config_calls, load_refs_calls


def test_cmd_rebuild_dispatches_without_external_input(monkeypatch) -> None:
    cfg, refs, rebuild_calls, setup_calls, load_config_calls, load_refs_calls = _patch_dependencies(monkeypatch)

    cli_rebuild.cmd_rebuild(_args(debug=True))

    assert load_config_calls == ["config.ini"]
    assert setup_calls == [(cfg.log_file, True)]
    assert load_refs_calls == [()]
    assert len(rebuild_calls) == 1
    called_cfg, called_refs, called_log = rebuild_calls[0]
    assert called_cfg is cfg
    assert called_refs is refs
    assert isinstance(called_log, logging.Logger)
    assert called_log.name == "forza"
