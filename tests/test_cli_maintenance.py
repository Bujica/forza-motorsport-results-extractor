from __future__ import annotations

from enum import Enum
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from forza.cli import maintenance as cli_maintenance
from forza.exceptions import ConfigValidationError


class _SchemaState(Enum):
    CURRENT = "current"
    UNMANAGED = "unmanaged"


class _FakeDatabaseService:
    def __init__(self, database_file: Path, status=None) -> None:
        self.database_file = database_file
        self.status_obj = status
        self.entered = False
        self.exited = False
        self.seed_calls = []

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *_exc_info) -> None:
        self.exited = True

    def status(self):
        return self.status_obj

    def seed_references(self, *, tracks, cars):
        self.seed_calls.append((list(tracks), list(cars)))
        return len(tracks), len(cars)


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(
        log_file=Path("forza.log"),
        database_file=Path("data/forza.sqlite3"),
    )


def _args(**overrides) -> SimpleNamespace:
    defaults = {"config": "config.ini", "debug": False}
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _patch_load_and_logging(monkeypatch):
    cfg = _cfg()
    load_config_calls = []
    setup_calls = []
    monkeypatch.setattr(cli_maintenance, "load_config", lambda config: load_config_calls.append(config) or cfg)
    monkeypatch.setattr(cli_maintenance, "setup_logging", lambda log_file, *, debug: setup_calls.append((log_file, debug)))
    return cfg, load_config_calls, setup_calls


def _install_fake_migrate_module(monkeypatch, *, state: _SchemaState):
    calls = {"detect": [], "upgrade": []}
    module = ModuleType("forza.db.migrate")
    module.DatabaseSchemaState = _SchemaState

    def detect_database_state(database_file):
        calls["detect"].append(database_file)
        return state

    def upgrade_database(database_file):
        calls["upgrade"].append(database_file)

    module.detect_database_state = detect_database_state
    module.upgrade_database = upgrade_database
    monkeypatch.setitem(__import__("sys").modules, "forza.db.migrate", module)
    return calls


def test_cmd_db_status_prints_status_and_uses_read_only_service(monkeypatch, capsys) -> None:
    cfg, load_config_calls, setup_calls = _patch_load_and_logging(monkeypatch)
    status = SimpleNamespace(
        database_file=cfg.database_file,
        database_exists=True,
        schema_state="current",
        current_revision="abc",
        head_revision="abc",
        image_files=1,
        extraction_runs=2,
        extraction_results=3,
        lap_records=4,
        review_cases=5,
        image_flags=6,
        export_artifacts=7,
    )
    services = []
    monkeypatch.setattr(
        cli_maintenance,
        "DatabaseService",
        lambda database_file: services.append(_FakeDatabaseService(database_file, status)) or services[-1],
    )

    cli_maintenance.cmd_db_status(_args(debug=True))

    assert load_config_calls == ["config.ini"]
    assert setup_calls == [(cfg.log_file, True)]
    assert services[0].database_file == cfg.database_file
    assert services[0].entered is True
    assert services[0].exited is True
    out = capsys.readouterr().out
    assert "Database: data\\forza.sqlite3" in out
    assert "Exists:   True" in out
    assert "Schema:   current" in out
    assert "Revision: abc" in out
    assert "image_files     : 1" in out
    assert "export_artifacts  : 7" in out


def test_cmd_db_reset_requires_yes_before_loading_config(monkeypatch) -> None:
    monkeypatch.setattr(cli_maintenance, "load_config", lambda _config: pytest.fail("config should not load"))

    with pytest.raises(SystemExit, match="Refusing to reset database without --yes"):
        cli_maintenance.cmd_db_reset(_args(yes=False))


def test_cmd_db_reset_deletes_database_and_sqlite_sidecars(monkeypatch, tmp_path, capsys) -> None:
    cfg, load_config_calls, _setup_calls = _patch_load_and_logging(monkeypatch)
    cfg.database_file = tmp_path / "data" / "forza.sqlite3"
    cfg.database_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.database_file.write_text("db", encoding="utf-8")
    Path(f"{cfg.database_file}-wal").write_text("wal", encoding="utf-8")
    Path(f"{cfg.database_file}-shm").write_text("shm", encoding="utf-8")

    cli_maintenance.cmd_db_reset(_args(yes=True))

    assert load_config_calls == ["config.ini"]
    assert not cfg.database_file.exists()
    assert not Path(f"{cfg.database_file}-wal").exists()
    assert not Path(f"{cfg.database_file}-shm").exists()
    out = capsys.readouterr().out
    assert "Database reset" in out
    assert "Removed: 3 file(s)" in out


def test_cmd_db_upgrade_runs_upgrade_and_seeds_initial_references(monkeypatch, capsys) -> None:
    cfg, load_config_calls, setup_calls = _patch_load_and_logging(monkeypatch)
    calls = _install_fake_migrate_module(monkeypatch, state=_SchemaState.CURRENT)
    seed_calls = []

    def fake_seed(database_file):
        seed_calls.append(database_file)
        return 2, 1

    monkeypatch.setattr(cli_maintenance, "seed_initial_reference_text_files", fake_seed)

    cli_maintenance.cmd_db_upgrade(_args(debug=True))

    assert load_config_calls == ["config.ini"]
    assert setup_calls == [(cfg.log_file, True)]
    assert calls["detect"] == [cfg.database_file]
    assert calls["upgrade"] == [cfg.database_file]
    assert seed_calls == [cfg.database_file]
    out = capsys.readouterr().out
    assert "Upgrading database: data\\forza.sqlite3" in out
    assert "Seeded references: 2 track(s), 1 car(s) added." in out
    assert "Done." in out


def test_cmd_db_upgrade_rejects_unmanaged_database(monkeypatch, capsys) -> None:
    cfg, _load_config_calls, _setup_calls = _patch_load_and_logging(monkeypatch)
    calls = _install_fake_migrate_module(monkeypatch, state=_SchemaState.UNMANAGED)

    with pytest.raises(SystemExit) as exc_info:
        cli_maintenance.cmd_db_upgrade(_args())

    assert exc_info.value.code == 1
    assert calls["detect"] == [cfg.database_file]
    assert calls["upgrade"] == []
    out = capsys.readouterr().out
    assert "ERROR: Unmanaged database detected" in out
    assert "db-reset --yes" in out


def test_cmd_config_check_reports_valid_config(monkeypatch, capsys) -> None:
    cfg, load_config_calls, _setup_calls = _patch_load_and_logging(monkeypatch)
    validate_calls = []
    monkeypatch.setattr("forza.config.validate_config", lambda cfg_arg: validate_calls.append(cfg_arg))

    cli_maintenance.cmd_config_check(_args())

    assert load_config_calls == ["config.ini"]
    assert validate_calls == [cfg]
    assert capsys.readouterr().out == "Configuration is valid. (config.ini)\n"


def test_cmd_config_check_exits_when_config_cannot_be_loaded(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli_maintenance, "load_config", lambda config: (_ for _ in ()).throw(RuntimeError("bad config")))

    with pytest.raises(SystemExit) as exc_info:
        cli_maintenance.cmd_config_check(_args())

    assert exc_info.value.code == 1
    assert capsys.readouterr().out == "ERROR: Could not load config: bad config\n"


def test_cmd_config_check_exits_for_validation_error(monkeypatch, capsys) -> None:
    cfg, _load_config_calls, _setup_calls = _patch_load_and_logging(monkeypatch)

    def fail_validation(cfg_arg):
        assert cfg_arg is cfg
        raise ConfigValidationError("invalid config")

    monkeypatch.setattr("forza.config.validate_config", fail_validation)

    with pytest.raises(SystemExit) as exc_info:
        cli_maintenance.cmd_config_check(_args())

    assert exc_info.value.code == 1
    assert capsys.readouterr().out == "invalid config\n"
