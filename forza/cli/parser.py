from __future__ import annotations

import argparse

from ..version import APP_DISPLAY_NAME, APP_DISPLAY_VERSION

from .export import cmd_export
from .gui import cmd_gui
from .maintenance import (
    cmd_config_check,
    cmd_db_doctor,
    cmd_db_reset,
    cmd_db_status,
    cmd_db_upgrade,
)
from .rebuild import cmd_rebuild
from .run import cmd_run


HELP_EPILOG = """
------------------------------------------------------------
 NORMAL WORKFLOW
------------------------------------------------------------

  python -m forza
      Process all new screenshots in the input folder.

  python -m forza --limit 5
      Process only the first 5 selected screenshots by file modified time.

  python -m forza --dry-run
      List new images that would be processed; no LLM calls.

  python -m forza --force
      Reprocess all images currently in input_dir.

  python -m forza --retry-errors
      Reprocess only images whose latest extraction result is error.

  python -m forza gui
      Open the optional PySide6 desktop interface.

------------------------------------------------------------
 MANUAL CORRECTIONS (no LLM calls)
------------------------------------------------------------

  python -m forza rebuild
      Regenerate reports from the current SQLite state.
  python -m forza config-check
      Validate forza_config.ini and report any errors.

  python -m forza maintenance db-status
      Inspect the relational database. Read-only.

  python -m forza maintenance db-doctor
      Run read-only relational integrity checks before reruns or releases.

  python -m forza maintenance db-doctor --json
      Emit the same DB Doctor checks as structured JSON.

  python -m forza maintenance db-upgrade
      Create the database or apply pending Alembic migrations.

  python -m forza maintenance db-reset --yes
      Delete the configured SQLite database before rebuilding a clean schema.

------------------------------------------------------------
DIAGNOSTICS
------------------------------------------------------------

  Use the GUI Diagnostics section for Image Debug, DB Doctor,
  and logs. Experimental workbench commands are no longer public CLI.
"""


def build_parser() -> argparse.ArgumentParser:
    root_shared = argparse.ArgumentParser(add_help=False)
    root_shared.add_argument("--config", default="forza_config.ini", metavar="FILE")
    root_shared.add_argument("--debug", action="store_true", default=False)

    sub_shared = argparse.ArgumentParser(add_help=False)
    sub_shared.add_argument("--config", default=argparse.SUPPRESS, metavar="FILE")
    sub_shared.add_argument("--debug", action="store_true", default=argparse.SUPPRESS)

    root = argparse.ArgumentParser(
        prog="python -m forza",
        description=APP_DISPLAY_NAME,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=HELP_EPILOG,
        parents=[root_shared],
    )
    root.add_argument("--version", action="version", version=APP_DISPLAY_VERSION)
    root.add_argument("--dry-run", action="store_true")
    root.add_argument("--force", action="store_true")
    root.add_argument("--retry-errors", action="store_true")
    root.add_argument("--limit", type=int, default=None, metavar="N", help="process only the first N input images")
    root.set_defaults(func=cmd_run)

    sub = root.add_subparsers(title="subcommands")

    p_gui = sub.add_parser("gui", parents=[sub_shared])
    p_gui.set_defaults(func=cmd_gui)

    p_run = sub.add_parser("run", parents=[sub_shared])
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--force", action="store_true")
    p_run.add_argument("--retry-errors", action="store_true")
    p_run.add_argument("--limit", type=int, default=None, metavar="N", help="process only the first N input images")
    p_run.set_defaults(func=cmd_run)

    p_rebuild = sub.add_parser("rebuild", parents=[sub_shared])
    p_rebuild.set_defaults(func=cmd_rebuild)

    p_export = sub.add_parser("export", parents=[sub_shared])
    p_export.add_argument("--out", default=None, metavar="FILE")
    p_export.set_defaults(func=cmd_export)

    p_config_check = sub.add_parser("config-check", parents=[sub_shared])
    p_config_check.set_defaults(func=cmd_config_check)

    p_maintenance = sub.add_parser("maintenance", parents=[sub_shared])
    maintenance_sub = p_maintenance.add_subparsers(title="maintenance_commands", required=True)

    p_db = maintenance_sub.add_parser("db-status", parents=[sub_shared])
    p_db.set_defaults(func=cmd_db_status)

    p_db_upgrade = maintenance_sub.add_parser("db-upgrade", parents=[sub_shared])
    p_db_upgrade.set_defaults(func=cmd_db_upgrade)

    p_db_reset = maintenance_sub.add_parser("db-reset", parents=[sub_shared])
    p_db_reset.add_argument("--yes", action="store_true")
    p_db_reset.set_defaults(func=cmd_db_reset)

    p_db_doctor = maintenance_sub.add_parser("db-doctor", parents=[sub_shared])
    p_db_doctor.add_argument("--json", action="store_true")
    p_db_doctor.set_defaults(func=cmd_db_doctor)

    return root
