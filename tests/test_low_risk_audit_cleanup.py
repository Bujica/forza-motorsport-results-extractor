from __future__ import annotations

import inspect

import pytest
from sqlmodel import Session, select

from forza.application.gui_write_service import GuiWriteService
from forza.application.rebuild_service import RebuildService
from forza.db.models import ExtractionAttemptEntity
from forza.db.repositories import ExtractionResultRepository
from forza.events import EventType
from forza.schemas import ModelExtractionAttempt

from tests._db_repository_helpers import make_engine


def test_rebuild_service_uses_typed_review_cases_event() -> None:
    source = inspect.getsource(RebuildService.rebuild_outputs)

    assert "EventType.REVIEW_CASES_CREATED" in source
    assert "review_cases_created" not in source
    assert EventType.REVIEW_CASES_CREATED.value == "review_cases_created"


def test_set_lap_dirty_has_no_dead_affected_groups_local() -> None:
    source = inspect.getsource(GuiWriteService.set_lap_dirty)

    assert "affected_groups" not in source


def test_append_attempt_rejects_missing_extraction_result_parent(tmp_path) -> None:
    engine = make_engine(tmp_path)

    with Session(engine) as session:
        repository = ExtractionResultRepository(session)

        with pytest.raises(ValueError, match="extraction_result_id does not exist"):
            repository.append_attempt(
                ModelExtractionAttempt(attempt_number=1, status="ok", accepted=True),
                extraction_result_id="missing-result",
                run_id="run-missing-result",
                image_file_id="image-missing-result",
            )

        assert session.exec(select(ExtractionAttemptEntity)).all() == []
