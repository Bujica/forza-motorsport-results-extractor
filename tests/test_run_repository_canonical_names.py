from __future__ import annotations

from pathlib import Path

from sqlmodel import Session

from forza.db import create_sqlite_engine
from forza.db.repositories import RunRepository
from forza.db.testing import create_test_db_and_tables
from forza.schemas import RunStatus


def _engine(tmp_path: Path):
    engine = create_sqlite_engine(tmp_path / "forza.sqlite3")
    create_test_db_and_tables(engine)
    return engine


def test_run_repository_create_and_upsert_use_prompt_name(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    with Session(engine) as session:
        repo = RunRepository(session)
        created = repo.create(
            run_id="run-canonical-prompt",
            backend="lmstudio",
            model="qwen",
            prompt_name="prompt-a",
        )
        session.commit()

        assert created.prompt_name == "prompt-a"

        updated = repo.upsert(
            run_id="run-canonical-prompt",
            backend="lmstudio",
            model="qwen",
            status=RunStatus.COMPLETED,
            prompt_name="prompt-b",
        )
        session.commit()

        assert updated.prompt_name == "prompt-b"


def test_run_repository_complete_uses_operational_error_message_metric(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    with Session(engine) as session:
        repo = RunRepository(session)
        repo.create(run_id="run-operational-error", backend="lmstudio", model="qwen")
        repo.complete(
            "run-operational-error",
            status=RunStatus.FAILED,
            metrics={
                "operational_error_message": "cancelled_by_user",
                "diagnostic_probe": "kept-as-config-extra",
            },
        )
        session.commit()

        entity = repo.by_id("run-operational-error")

    assert entity is not None
    assert entity.operational_error_message == "cancelled_by_user"
    assert not hasattr(entity, "config")

    schema = repo.to_schema(entity)
    assert schema.run_config["diagnostic_probe"] == "kept-as-config-extra"


def test_run_repository_rejects_legacy_run_api_names() -> None:
    source = Path("forza/db/repositories/runs.py").read_text(encoding="utf-8")

    assert "prompt" + "_version" not in source
    assert '"error_message"' not in source
    assert "operational_error_message" in source
