from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

from ..db.migrate import detect_database_state


@dataclass(frozen=True)
class FastDbReport:
    schema_state: str
    ok: bool
    errors: int
    warnings: int


def fast_db_report(database_file: Path) -> FastDbReport:
    """Return quick operational health checks for GUI Developer Overview.

    The full DB Doctor remains the release gate. This helper stays in the
    application layer so the GUI package does not import the database layer.
    """
    schema_state = detect_database_state(database_file).value
    if schema_state != "current":
        return FastDbReport(schema_state=schema_state, ok=False, errors=1, warnings=0)
    errors = 0
    warnings = 0
    pending_best_lap_sql = (
        "SELECT COUNT(*) "
        "FROM image_files si "
        "JOIN lap_records lr ON lr.image_file_id = si.id "
        "WHERE si.best_lap_status = 'pending' "
        "AND si.file_status = 'available' "
        "AND lr.dirty = 0 "
        "AND COALESCE(lr.best_lap_ms, 0) > 0"
    )
    with sqlite3.connect(database_file) as con:
        quick_check = con.execute("PRAGMA quick_check").fetchone()
        if not quick_check or str(quick_check[0]).lower() != "ok":
            errors += 1
        errors += _scalar_sql(con, "PRAGMA foreign_key_check")
        errors += _scalar_sql(con, pending_best_lap_sql)
    return FastDbReport(schema_state=schema_state, ok=errors == 0, errors=errors, warnings=warnings)


def _scalar_sql(con: sqlite3.Connection, sql: str) -> int:
    try:
        rows = con.execute(sql).fetchall()
    except sqlite3.Error:
        return 1
    if sql.strip().lower().startswith("pragma foreign_key_check"):
        return len(rows)
    if not rows:
        return 0
    return int(rows[0][0] or 0)
