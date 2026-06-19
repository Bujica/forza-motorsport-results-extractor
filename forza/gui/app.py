from __future__ import annotations

import sys
from pathlib import Path

from ..config import load_config
from ..version import APP_DISPLAY_NAME, __version__
from ..application.gui_database_state import apply_database_reset, apply_database_upgrade, inspect_database


def run_gui(*, config_path: str | Path = "forza_config.ini", debug: bool = False) -> int:
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        print(
            "PySide6 is not installed. Install the GUI with: pip install -e .[gui]",
            file=sys.stderr,
        )
        return 2

    from .main_window import MainWindow
    from .theme import build_qss

    cfg = load_config(config_path)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setApplicationVersion(__version__)
    app.setStyleSheet(build_qss())

    check = inspect_database(cfg.database_file)
    if not check.opened:
        if check.state.value in {"missing", "empty", "outdated"}:
            answer = QMessageBox.question(
                None,
                "Database State",
                check.message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return 1
            check = apply_database_upgrade(cfg.database_file)
        elif check.state.value == "unmanaged":
            answer = QMessageBox.warning(
                None,
                "Reset Database",
                (
                    f"{check.message}\n\n"
                    f"Reset and recreate this database now?\n\n{cfg.database_file}"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return 1
            check = apply_database_reset(cfg.database_file)
        else:
            QMessageBox.critical(None, "Database Blocked", check.message)
            return 1

    if not check.opened:
        QMessageBox.critical(None, "Database Blocked", check.message)
        return 1

    window = MainWindow(
        cfg=cfg,
        config_path=str(config_path),
        debug=debug,
        database_path=str(cfg.database_file),
        schema_state=check.state.value,
    )
    window.show()
    return app.exec()
