from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from forza.cli import export as cli_export


class _FakeExportService:
    def __init__(self, rows: int, calls: list) -> None:
        self._rows = rows
        self._calls = calls

    def clean_csv(self, cfg, out: Path) -> int:
        self._calls.append((cfg, out))
        return self._rows


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(log_file=Path("forza.log"))


def _args(*, out: str | None = None, debug: bool = False) -> SimpleNamespace:
    return SimpleNamespace(config="config.ini", debug=debug, out=out)


def _patch_dependencies(monkeypatch, *, rows: int):
    cfg = _cfg()
    calls = []
    setup_calls = []
    load_config_calls = []
    monkeypatch.setattr(cli_export, "load_config", lambda config: load_config_calls.append(config) or cfg)
    monkeypatch.setattr(cli_export, "setup_logging", lambda log_file, *, debug: setup_calls.append((log_file, debug)))
    monkeypatch.setattr(cli_export, "ExportService", lambda: _FakeExportService(rows, calls))
    return cfg, calls, setup_calls, load_config_calls


def test_cmd_export_uses_default_output_and_prints_when_rows_exported(monkeypatch, capsys) -> None:
    cfg, calls, setup_calls, load_config_calls = _patch_dependencies(monkeypatch, rows=7)

    cli_export.cmd_export(_args(debug=True))

    assert load_config_calls == ["config.ini"]
    assert setup_calls == [(cfg.log_file, True)]
    assert calls == [(cfg, Path("output") / "exports" / "results.csv")]
    assert capsys.readouterr().out == "Exported 7 rows -> output\\exports\\results.csv\n"


def test_cmd_export_uses_custom_output(monkeypatch, capsys) -> None:
    cfg, calls, _setup_calls, _load_config_calls = _patch_dependencies(monkeypatch, rows=1)

    cli_export.cmd_export(_args(out="custom/results.csv"))

    assert calls == [(cfg, Path("custom/results.csv"))]
    assert "Exported 1 rows -> custom" in capsys.readouterr().out


def test_cmd_export_does_not_print_when_no_rows_exported(monkeypatch, capsys) -> None:
    cfg, calls, _setup_calls, _load_config_calls = _patch_dependencies(monkeypatch, rows=0)

    cli_export.cmd_export(_args(out="empty.csv"))

    assert calls == [(cfg, Path("empty.csv"))]
    assert capsys.readouterr().out == ""
