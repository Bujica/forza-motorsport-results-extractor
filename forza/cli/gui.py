from __future__ import annotations


def cmd_gui(args) -> None:
    from ..gui.app import run_gui

    raise SystemExit(run_gui(config_path=args.config, debug=args.debug))
