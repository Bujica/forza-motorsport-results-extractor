"""
Central logging setup for the forza package.

Usage (in __main__.py, replacing the inline _setup_logging):
    from forza.logging_setup import setup_logging
    setup_logging(cfg.log_file, debug=args.debug)

Log files:
    logs/app.log     — INFO and above, rotating (5 MB × 3 backups)
    logs/errors.log  — WARNING and above only, rotating (2 MB × 3 backups)

Console output mirrors the operator-facing log level requested by --debug.
Verbose third-party diagnostics stay out of normal console/GUI output.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path


_FMT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
_DATE = "%Y-%m-%d %H:%M:%S"

# Maximum size per log file before rotation (bytes)
_APP_MAX_BYTES   = 5 * 1024 * 1024   # 5 MB
_ERR_MAX_BYTES   = 2 * 1024 * 1024   # 2 MB
_BACKUP_COUNT    = 3


def setup_logging(log_file: Path, *, debug: bool = False) -> None:
    """
    Configure the root logger with three handlers:

    1. app.log        — rotating file, DEBUG+, full detail
    2. errors.log     — rotating file, WARNING+, errors only
    3. StreamHandler  — console, INFO (or DEBUG with --debug)

    Calling this function a second time replaces all handlers cleanly,
    so it is safe to call once per CLI invocation.

    Parameters
    ----------
    log_file : Path
        Base path for the main log file.  The errors log is written to
        the same directory as <stem>_errors<suffix>
        (e.g. forza_debug.log → forza_debug_errors.log).
    debug : bool
        When True, the console handler emits DEBUG messages.
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Remove any handlers already attached (idempotent re-init)
    for h in root.handlers[:]:
        try:
            h.close()
        except Exception:
            pass
    root.handlers.clear()

    formatter = logging.Formatter(_FMT, datefmt=_DATE)

    # ── 1. app.log (DEBUG+, rotating) ────────────────────────────────────────
    log_file.parent.mkdir(parents=True, exist_ok=True)
    app_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=_APP_MAX_BYTES, backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    app_handler.setLevel(logging.DEBUG)
    app_handler.setFormatter(formatter)

    # ── 2. errors.log (WARNING+, rotating) ───────────────────────────────────
    errors_log = log_file.parent / f"{log_file.stem}_errors{log_file.suffix}"
    err_handler = logging.handlers.RotatingFileHandler(
        errors_log, maxBytes=_ERR_MAX_BYTES, backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    err_handler.setLevel(logging.WARNING)
    err_handler.setFormatter(formatter)

    # ── 3. Console (INFO or DEBUG) ────────────────────────────────────────────
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if debug else logging.INFO)
    console.setFormatter(formatter)

    root.addHandler(app_handler)
    root.addHandler(err_handler)
    root.addHandler(console)

    # Silence noisy third-party loggers in normal operation. Warnings and
    # errors still propagate; repetitive INFO diagnostics do not.
    for noisy in (
        "PIL",
        "urllib3",
        "httpx",
        "httpcore",
        "alembic",
        "alembic.runtime.migration",
        "sqlalchemy.engine",
        "sqlalchemy.pool",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)
