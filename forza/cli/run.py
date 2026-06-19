from __future__ import annotations

import argparse
import logging

from ..config import load_config
from ..logging_setup import setup_logging
from ..application import DatabaseService, RunOptions, RunService


def cmd_run(args: argparse.Namespace) -> None:
    cfg = load_config(args.config, strict=True)
    setup_logging(cfg.log_file, debug=args.debug)
    log = logging.getLogger("forza")
    with DatabaseService(cfg.database_file) as database:
        refs = database.load_reference_data()

    status = RunService().run(
        cfg,
        refs,
        log,
        options=RunOptions(
            dry_run=args.dry_run,
            force=args.force,
            retry_errors=getattr(args, "retry_errors", False),
            max_images=getattr(args, "limit", None),
        ),
    )
    if status == "cancelled":
        raise SystemExit(130)
    if status != "completed":
        raise SystemExit(1)
