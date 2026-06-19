from __future__ import annotations

import argparse
import logging

from ..config import load_config
from ..logging_setup import setup_logging
from ..application import DatabaseService, RebuildService


def cmd_rebuild(args: argparse.Namespace) -> None:
    log = logging.getLogger("forza")
    cfg = load_config(args.config)
    setup_logging(cfg.log_file, debug=args.debug)

    service = RebuildService()

    with DatabaseService(cfg.database_file) as database:
        refs = database.load_reference_data()
    log.info("Rebuild: regenerating artifacts from SQLite; no model calls")
    service.rebuild_outputs(cfg, refs, log)

