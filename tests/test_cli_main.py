from __future__ import annotations

from types import SimpleNamespace

from forza.cli import main as cli_main


class _FakeParser:
    def __init__(self, func):
        self.func = func
        self.parse_calls = 0

    def parse_args(self):
        self.parse_calls += 1
        return SimpleNamespace(func=self.func, parsed=True)


def test_main_dispatches_to_parsed_command_function(monkeypatch) -> None:
    calls = []

    def command(args) -> None:
        calls.append(args)

    parser = _FakeParser(command)
    monkeypatch.setattr(cli_main, "build_parser", lambda: parser)
    monkeypatch.setattr("sys.argv", ["forza", "run"])

    cli_main.main()

    assert parser.parse_calls == 1
    assert len(calls) == 1
    assert calls[0].parsed is True


def test_main_maps_question_mark_argument_to_help(monkeypatch) -> None:
    calls = []

    def command(args) -> None:
        calls.append(args)

    parser = _FakeParser(command)
    argv = ["forza", "?"]
    monkeypatch.setattr(cli_main, "build_parser", lambda: parser)
    monkeypatch.setattr("sys.argv", argv)

    cli_main.main()

    assert argv == ["forza", "--help"]
    assert parser.parse_calls == 1
    assert len(calls) == 1
