from __future__ import annotations

from sqlalchemy import text
from sqlmodel import Session

from .contracts import DbDoctorCheck


def schema_head_check(schema_state: str) -> DbDoctorCheck | None:
    if schema_state == "current":
        return None
    return DbDoctorCheck(
        "schema_head",
        "error",
        1,
        "Database schema is not at Alembic head.",
    )


def sqlite_integrity_check(session: Session) -> DbDoctorCheck:
    return DbDoctorCheck(
        "sqlite_integrity_check",
        "error",
        _sqlite_integrity_errors(session),
        "SQLite integrity_check must report ok.",
    )


def foreign_key_violations_check(session: Session) -> DbDoctorCheck:
    return DbDoctorCheck(
        "foreign_key_violations",
        "error",
        _foreign_key_violations(session),
        "SQLite foreign_key_check must report no violations.",
    )


def _sqlite_integrity_errors(session: Session) -> int:
    rows = session.exec(text("PRAGMA integrity_check")).all()
    messages = [
        str(row[0] if isinstance(row, tuple) or hasattr(row, "__getitem__") else row)
        for row in rows
    ]
    return sum(1 for message in messages if message.casefold() != "ok")


def _foreign_key_violations(session: Session) -> int:
    return len(session.exec(text("PRAGMA foreign_key_check")).all())
