from __future__ import annotations

from forza.application.database_service import DatabaseService
from forza.application.run_service import RunServiceDatabase


def test_database_service_satisfies_run_service_database_protocol(tmp_path) -> None:
    """Regression for S-1/S-4: RunServiceDatabase documents exactly what
    RunService needs from `database`, replacing scattered getattr/hasattr
    duck-typing with one explicit, checkable contract. If DatabaseService
    ever drops or renames one of these methods, this test catches it instead
    of a silent AttributeError deep inside a run.
    """
    db = DatabaseService(tmp_path / "forza.sqlite3", auto_upgrade=True)
    try:
        assert isinstance(db, RunServiceDatabase)
    finally:
        db.close()
