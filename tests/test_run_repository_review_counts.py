from __future__ import annotations

from pathlib import Path

from sqlmodel import Session

from forza.db import create_sqlite_engine
from forza.db.migrate import upgrade_database
from forza.db.models import ExtractionRunEntity, ReviewCaseEntity
from forza.db.repositories import RunRepository
from forza.schemas import RunStatus


def _prepare_session(tmp_path: Path) -> Session:
    db_path = tmp_path / "forza.sqlite3"
    upgrade_database(db_path)
    engine = create_sqlite_engine(db_path)
    return Session(engine)


def _create_run(repo: RunRepository, run_id: str) -> None:
    repo.create(
        run_id=run_id,
        backend="lmstudio",
        model="model",
        status=RunStatus.COMPLETED,
        prompt_name="prompt",
        input_dir="input",
    )


def _review_case(case_id: str, *, run_id: str, status: str, case_number: int) -> ReviewCaseEntity:
    return ReviewCaseEntity(
        id=case_id,
        run_id=run_id,
        case_number=case_number,
        reason="track",
        status=status,
        business_key=f"case:{case_id}",
    )


def test_refresh_review_counts_can_scope_to_specific_runs(tmp_path: Path) -> None:
    with _prepare_session(tmp_path) as session:
        repo = RunRepository(session)
        _create_run(repo, "run-a")
        _create_run(repo, "run-b")
        session.flush()
        session.add(_review_case("a-open", run_id="run-a", status="open", case_number=1))
        session.add(_review_case("a-resolved", run_id="run-a", status="resolved", case_number=2))
        session.add(_review_case("b-open", run_id="run-b", status="open", case_number=3))
        session.commit()

        run_a = session.get(ExtractionRunEntity, "run-a")
        run_b = session.get(ExtractionRunEntity, "run-b")
        assert run_a is not None
        assert run_b is not None
        run_a.review_case_count = 99
        run_b.review_case_count = 99
        session.add(run_a)
        session.add(run_b)
        session.commit()

        repo.refresh_review_counts(run_ids=["run-a"])
        session.commit()

        assert session.get(ExtractionRunEntity, "run-a").review_case_count == 1
        assert session.get(ExtractionRunEntity, "run-b").review_case_count == 99


def test_refresh_review_counts_without_scope_updates_all_runs(tmp_path: Path) -> None:
    with _prepare_session(tmp_path) as session:
        repo = RunRepository(session)
        _create_run(repo, "run-a")
        _create_run(repo, "run-b")
        session.flush()
        session.add(_review_case("a-open", run_id="run-a", status="open", case_number=1))
        session.add(_review_case("b-open", run_id="run-b", status="open", case_number=2))
        session.add(_review_case("b-ignored", run_id="run-b", status="ignored", case_number=3))
        session.commit()

        repo.refresh_review_counts()
        session.commit()

        assert session.get(ExtractionRunEntity, "run-a").review_case_count == 1
        assert session.get(ExtractionRunEntity, "run-b").review_case_count == 1
