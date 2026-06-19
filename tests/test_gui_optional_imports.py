from __future__ import annotations

import builtins
import importlib


def test_cli_parser_imports_without_pyside6() -> None:
    parser_module = importlib.import_module("forza.cli.parser")
    parser = parser_module.build_parser()

    args = parser.parse_args(["gui"])

    assert callable(args.func)


def test_gui_command_reports_missing_pyside6(monkeypatch, capsys) -> None:
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "PySide6" or name.startswith("PySide6."):
            raise ImportError("blocked for optional dependency test")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    from forza.gui.app import run_gui

    assert run_gui(config_path="forza_config.ini") == 2
    assert "pip install -e .[gui]" in capsys.readouterr().err
