from __future__ import annotations

from pathlib import Path

import pytest

from forza.db.migrate import DatabaseSchemaState
from forza.application import gui_database_state as database_state


@pytest.mark.parametrize(
    ("schema_state", "opened", "message_token"),
    [
        (DatabaseSchemaState.CURRENT, True, "Database is current"),
        (DatabaseSchemaState.MISSING, False, "Create the database"),
        (DatabaseSchemaState.EMPTY, False, "Create the database"),
        (DatabaseSchemaState.OUTDATED, False, "Upgrade is required"),
        (DatabaseSchemaState.UNMANAGED, False, "db-reset"),
        (DatabaseSchemaState.ERROR, False, "corrupted"),
    ],
)
def test_inspect_database_covers_all_schema_states(
    monkeypatch,
    tmp_path: Path,
    schema_state: DatabaseSchemaState,
    opened: bool,
    message_token: str,
) -> None:
    db = tmp_path / "forza.sqlite3"
    monkeypatch.setattr(database_state, "detect_database_state", lambda path: schema_state)

    result = database_state.inspect_database(db)

    assert result.opened is opened
    assert result.state == schema_state
    assert message_token in result.message


def test_upgrade_database_uses_real_upgrade_api(monkeypatch, tmp_path: Path) -> None:
    db = tmp_path / "forza.sqlite3"
    upgrade_calls: list[Path] = []
    seed_calls: list[Path] = []

    def fake_upgrade(path: Path) -> None:
        upgrade_calls.append(path)

    def fake_seed(path: Path) -> tuple[int, int]:
        seed_calls.append(path)
        return 74, 604

    monkeypatch.setattr(database_state, "upgrade_database", fake_upgrade)
    monkeypatch.setattr(database_state, "seed_initial_reference_text_files", fake_seed)
    monkeypatch.setattr(database_state, "detect_database_state", lambda path: DatabaseSchemaState.CURRENT)

    result = database_state.apply_database_upgrade(db)

    assert upgrade_calls == [db]
    assert seed_calls == [db]
    assert result.opened is True
    assert "Seeded references: 74 track(s), 604 car(s) added." in result.message


def test_reset_database_removes_sqlite_files_then_upgrades(monkeypatch, tmp_path: Path) -> None:
    db = tmp_path / "forza.sqlite3"
    wal = tmp_path / "forza.sqlite3-wal"
    shm = tmp_path / "forza.sqlite3-shm"
    for path in (db, wal, shm):
        path.write_text("old", encoding="utf-8")
    upgrade_calls: list[Path] = []

    def fake_upgrade(path: Path) -> None:
        upgrade_calls.append(path)
        path.write_text("new", encoding="utf-8")

    monkeypatch.setattr(database_state, "upgrade_database", fake_upgrade)
    monkeypatch.setattr(database_state, "seed_initial_reference_text_files", lambda path: (1, 2))
    monkeypatch.setattr(database_state, "detect_database_state", lambda path: DatabaseSchemaState.CURRENT)

    result = database_state.apply_database_reset(db)

    assert result.opened is True
    assert upgrade_calls == [db]
    assert db.read_text(encoding="utf-8") == "new"
    assert not wal.exists()
    assert not shm.exists()
    assert "Removed 3 file(s)" in result.message
