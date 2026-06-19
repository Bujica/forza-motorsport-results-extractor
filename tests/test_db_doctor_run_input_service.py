from __future__ import annotations

from tests._db_doctor_service_helpers import *  # noqa: F403


def test_db_doctor_validates_prompt_snapshot_content_and_run_link(tmp_path, migrated_db_path: Path):
    db_path = migrated_db_path
    ids = _seed_valid_run(db_path)
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            run = session.get(ExtractionRunEntity, ids["run_id"])
            prompt = session.get(PromptSnapshotEntity, run.prompt_snapshot_id)
            prompt.system_text = "tampered"
            run.prompt_hash = "wrong"
            session.add(prompt)
            session.add(run)
            session.commit()
    finally:
        engine.dispose()

    _report, checks = _report_by_key(db_path)
    assert checks["prompt_snapshot_integrity_invalid"].count == 1
    assert checks["run_prompt_snapshot_mismatch"].count == 1

def test_db_doctor_validates_duplicate_input_links(tmp_path, migrated_db_path: Path):
    db_path = migrated_db_path
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            prompt_hash = prompt_payload_hash(
                system_text="prompt",
                user_text_template=None,
                response_schema_json=None,
            )
            prompt = PromptSnapshotEntity(
                id=f"main:{prompt_hash}",
                prompt_name="main",
                content_hash=prompt_hash,
                system_text="prompt",
            )
            run = ExtractionRunEntity(
                id="run-duplicate-invalid",
                status="completed",
                backend="lmstudio",
                model="qwen",
                prompt_snapshot_id=prompt.id,
                prompt_name=prompt.prompt_name,
                prompt_hash=prompt.content_hash,
                total_inputs=1,
                duplicate_count=1,
            )
            session.add(prompt)
            session.flush()
            session.add(run)
            session.flush()
            session.add(
                RunInputEntity(
                    run_id=run.id,
                    input_order=0,
                    input_path="duplicate.png",
                    file_name="duplicate.png",
                    extension=".png",
                    file_hash="hash-duplicate",
                    decision="duplicate",
                    duplicate_kind="batch",
                    duplicate_of_hash="hash-other",
                )
            )
            session.commit()
    finally:
        engine.dispose()

    _report, checks = _report_by_key(db_path)
    assert checks["run_input_duplicate_link_invalid"].count == 1

def test_db_doctor_reports_process_input_without_result(tmp_path, migrated_db_path: Path):
    db_path = migrated_db_path
    ids = _seed_valid_run(db_path)
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            session.add(
                RunInputEntity(
                    run_id=str(ids["run_id"]),
                    image_file_id=str(ids["image_file_id"]),
                    input_order=1,
                    input_path="second.png",
                    decision="process",
                )
            )
            session.commit()
    finally:
        engine.dispose()

    _report, checks = _report_by_key(db_path)

    assert checks["run_inputs_process_without_one_result"].count == 1
    assert checks["run_counters_mismatch"].count == 1

def test_db_doctor_reports_invalid_run_input_contract(tmp_path, migrated_db_path: Path):
    db_path = migrated_db_path
    ids = _seed_valid_run(db_path)
    engine = create_sqlite_engine(db_path)
    try:
        with Session(engine) as session:
            run_input = session.get(RunInputEntity, int(ids["run_input_id"]))
            run_input.process_reason = "full_run"
            run_input.skip_reason = "overloaded"
            session.add(run_input)
            session.commit()
    finally:
        engine.dispose()

    _report, checks = _report_by_key(db_path)

    assert checks["run_input_contract_invalid"].count == 1
