from __future__ import annotations

import argparse
from pathlib import Path

from ..config import load_config
from ..logging_setup import setup_logging
from ..application import ExportService


def cmd_export(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    setup_logging(cfg.log_file, debug=args.debug)
    out = Path(args.out) if args.out else (
        Path("output") / "exports" / "results.csv"
    )
    n = ExportService().clean_csv(cfg, out)
    if n:
        print(f"Exported {n} rows -> {out}")
