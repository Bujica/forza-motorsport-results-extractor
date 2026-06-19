"""Tests for Sprint 1–4 implementations.

Covers:
  P14 — emit_event sink isolation
  N1  — make_run_id uniqueness and format
  P13 — validate_config raises ConfigValidationError
  P3  — Alembic migrate module (upgrade, detect_state, is_up_to_date)
  P2  — db-status CLI is read-only
  P7  — ImageFile semantic_name field
  N3  — RunStatus enum values
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from forza.config import load_config, validate_config
from forza.db.migrate import (
    DatabaseSchemaState,
    detect_database_state,
    is_up_to_date,
    upgrade_database,
)
from forza.events import emit_event
from forza.exceptions import ConfigValidationError
from forza.schemas import (
    ExtractionRun,
    RunStatus,
)
from forza.application import DatabaseService
from forza.application.run_service import RunService


# ── P14 — emit_event sink isolation ──────────────────────────────────────────


def test_emit_event_sink_exception_does_not_crash_caller():
    def bad_sink(event):
        raise RuntimeError("GUI explodiu")

    # must not raise
    emit_event(bad_sink, "run_started", message="ok")


def test_emit_event_strict_reraises():
    def bad_sink(event):
        raise ValueError("controlled error")

    with pytest.raises(ValueError):
        emit_event(bad_sink, "run_started", strict=True)


def test_emit_event_none_sink_is_noop():
    emit_event(None, "run_started")  # must not raise


def test_emit_event_normal_sink_receives_event():
    received = []

    def good_sink(event):
        received.append(event)

    emit_event(good_sink, "run_started", run_id="r1", count=3)

    assert len(received) == 1
    assert received[0].type == "run_started"
    assert received[0].run_id == "r1"
    assert received[0].data["count"] == 3


# ── N1 — make_run_id ─────────────────────────────────────────────────────────

def test_make_run_id_is_unique():
    service = RunService()
    ids = {service.make_run_id() for _ in range(100)}
    assert len(ids) == 100


def test_make_run_id_format():
    run_id = RunService().make_run_id()
    # Format: YYYYMMDD_HHMMSS_xxxxxxxx
    parts = run_id.split("_")
    assert len(parts) == 3
    assert len(parts[0]) == 8 and parts[0].isdigit()   # YYYYMMDD
    assert len(parts[1]) == 6 and parts[1].isdigit()   # HHMMSS
    assert len(parts[2]) == 8                           # 8-char hex suffix


# ── P13 — validate_config ─────────────────────────────────────────────────────

def test_validate_config_passes_on_defaults(tmp_path):
    cfg = load_config(tmp_path / "missing.ini")
    validate_config(cfg)  # must not raise


def test_validate_config_raises_on_invalid_reasoning_mode(tmp_path):
    cfg = load_config(tmp_path / "missing.ini")
    cfg = dataclasses.replace(
        cfg, llm=dataclasses.replace(cfg.llm, reasoning_mode="invalid_reasoning")
    )
    with pytest.raises(ConfigValidationError, match="reasoning_mode="):
        validate_config(cfg)


def test_validate_config_raises_on_unknown_prompt(tmp_path):
    from forza.config import PromptConfig
    cfg = load_config(tmp_path / "missing.ini")
    cfg = dataclasses.replace(cfg, prompt=PromptConfig(active="does_not_exist"))
    with pytest.raises(ConfigValidationError, match="prompt"):
        validate_config(cfg)


def test_validate_config_raises_on_invalid_image_format(tmp_path):
    cfg = load_config(tmp_path / "missing.ini")
    cfg = dataclasses.replace(
        cfg, llm=dataclasses.replace(cfg.llm, image_format="bmp")
    )
    with pytest.raises(ConfigValidationError, match="image_format="):
        validate_config(cfg)


def test_validate_config_raises_on_invalid_workers(tmp_path):
    cfg = load_config(tmp_path / "missing.ini")
    cfg = dataclasses.replace(cfg, workers=0)
    with pytest.raises(ConfigValidationError, match="workers"):
        validate_config(cfg)


def test_validate_config_raises_on_inverted_temps(tmp_path):
    from forza.config import ValidationConfig
    cfg = load_config(tmp_path / "missing.ini")
    cfg = dataclasses.replace(
        cfg, validation=ValidationConfig(temp_min_f=150.0, temp_max_f=50.0)
    )
    with pytest.raises(ConfigValidationError, match="temp_min_f"):
        validate_config(cfg)


def test_validate_config_collects_multiple_errors(tmp_path):
    from forza.config import PromptConfig
    cfg = load_config(tmp_path / "missing.ini")
    cfg = dataclasses.replace(
        cfg,
        workers=0,
        prompt=PromptConfig(active="bad"),
        llm=dataclasses.replace(cfg.llm, image_format="bmp"),
    )
    with pytest.raises(ConfigValidationError) as exc_info:
        validate_config(cfg)
    msg = str(exc_info.value)
    assert "workers" in msg
    assert "prompt" in msg
    assert "image_format" in msg


# ── P3 — Alembic migrate ──────────────────────────────────────────────────────

def test_upgrade_database_creates_db(tmp_path):
    db = tmp_path / "forza.sqlite3"
    upgrade_database(db)
    assert db.exists()


def test_upgrade_database_is_idempotent(tmp_path):
    db = tmp_path / "forza.sqlite3"
    upgrade_database(db)
    upgrade_database(db)  # second call must not raise


def test_is_up_to_date_after_upgrade(tmp_path):
    db = tmp_path / "forza.sqlite3"
    upgrade_database(db)
    assert is_up_to_date(db) is True


def test_detect_state_missing(tmp_path):
    assert detect_database_state(tmp_path / "missing.sqlite3") == DatabaseSchemaState.MISSING


def test_detect_state_current_after_upgrade(tmp_path):
    db = tmp_path / "forza.sqlite3"
    upgrade_database(db)
    assert detect_database_state(db) == DatabaseSchemaState.CURRENT


def test_detect_state_rejects_incomplete_clean_break_shape_stamped_as_head(tmp_path):
    import sqlite3

    from forza.db.migrate import head_revision

    db = tmp_path / "incomplete-shape.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.executescript(
            """
            CREATE TABLE alembic_version (
                version_num VARCHAR(32) NOT NULL,
                CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
            );
            INSERT INTO alembic_version (version_num) VALUES ('0001_db_vnext_baseline');
            CREATE TABLE image_files (
                id VARCHAR NOT NULL,
                file_hash VARCHAR NOT NULL,
                PRIMARY KEY (id)
            );
            CREATE TABLE run_inputs (
                id INTEGER NOT NULL,
                PRIMARY KEY (id)
            );
            CREATE TABLE extraction_results (
                id VARCHAR NOT NULL,
                PRIMARY KEY (id)
            );
            CREATE TABLE extraction_attempts (
                id VARCHAR NOT NULL,
                PRIMARY KEY (id)
            );
            CREATE TABLE model_artifacts (
                id VARCHAR NOT NULL,
                PRIMARY KEY (id)
            );
            CREATE TABLE lap_records (
                id VARCHAR NOT NULL,
                PRIMARY KEY (id)
            );
            CREATE TABLE review_cases (
                id VARCHAR NOT NULL,
                PRIMARY KEY (id)
            );
            CREATE TABLE review_corrections (
                id VARCHAR NOT NULL,
                PRIMARY KEY (id)
            );
            CREATE TABLE image_flags (
                id VARCHAR NOT NULL,
                PRIMARY KEY (id)
            );
            """
        )
        connection.commit()

    assert head_revision() == "0001_db_vnext_baseline"
    assert detect_database_state(db) == DatabaseSchemaState.UNMANAGED


def test_detect_state_unmanaged(tmp_path):
    """A DB created via create_all (no alembic_version) must be detected as UNMANAGED."""
    from forza.db import create_sqlite_engine
    from forza.db.testing import create_test_db_and_tables
    db = tmp_path / "legacy.sqlite3"
    engine = create_sqlite_engine(db)
    create_test_db_and_tables(engine)
    engine.dispose()

    assert detect_database_state(db) == DatabaseSchemaState.UNMANAGED


def test_create_db_and_tables_is_not_public_db_api():
    import forza.db as db

    assert not hasattr(db, "create_db_and_tables")


def test_upgrade_raises_on_unmanaged_database(tmp_path):
    from forza.db import create_sqlite_engine
    from forza.db.testing import create_test_db_and_tables
    db = tmp_path / "legacy.sqlite3"
    engine = create_sqlite_engine(db)
    create_test_db_and_tables(engine)
    engine.dispose()

    with pytest.raises(RuntimeError, match="[Uu]nmanaged"):
        upgrade_database(db)


# ── P2 — db-status read-only ─────────────────────────────────────────────────

def test_db_status_does_not_create_database(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    status = DatabaseService(db_path).status()

    assert not db_path.exists()
    assert status.database_exists is False


def test_db_status_on_existing_db_does_not_mutate(tmp_path):
    db_path = tmp_path / "forza.sqlite3"
    upgrade_database(db_path)
    mtime_before = db_path.stat().st_mtime

    DatabaseService(db_path).status()

    # File modification time must not change (no writes)
    assert db_path.stat().st_mtime == mtime_before


# ── P7 — ImageFile semantic_name ───────────────────────────────────────────

def test_image_file_has_semantic_name_field(tmp_path):
    from forza.db import create_sqlite_engine
    from forza.db.testing import create_test_db_and_tables
    from forza.db.repositories import ImageFileRepository
    from sqlmodel import Session

    engine = create_sqlite_engine(tmp_path / "forza.sqlite3")
    create_test_db_and_tables(engine)
    with Session(engine) as session:
        repo = ImageFileRepository(session)
        entity = repo.upsert(
            file_hash="h1",
            file_name="raw.png",
            semantic_name="Track - A #1.png",
            current_name="Track - A #1.png",
        )
        session.commit()
        assert entity.semantic_name == "Track - A #1.png"
    engine.dispose()
