from __future__ import annotations

import os
import sys
from pathlib import Path


def _portable_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def _prepare_portable_cwd() -> None:
    """Keep relative config/data paths anchored at the portable bundle root."""
    os.chdir(_portable_root())


def main() -> None:
    _prepare_portable_cwd()
    if len(sys.argv) > 1:
        from forza.cli.main import main as cli_main

        cli_main()
        return

    from forza.gui.app import run_gui

    raise SystemExit(run_gui(config_path="forza_config.ini", debug=False))


if __name__ == "__main__":  # pragma: no cover
    main()
